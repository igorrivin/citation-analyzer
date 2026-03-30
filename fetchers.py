"""
Data fetchers for Semantic Scholar and Google Scholar.

Semantic Scholar: Free REST API, returns hIndex, citationCount, paperCount,
                  plus fieldsOfStudy per paper for field inference.
                  Rate limit: ~1 req/sec unauthenticated, 10 req/sec with API key.

Google Scholar:   Via `scholarly` library (no official API).
                  Returns hIndex, i10Index, citedby (total citations),
                  plus interest tags (self-reported field labels).
                  Rate-limited aggressively; may need proxy for heavy use.

                  Fallback: direct page fetch via browser when scholarly fails.
"""

import os
import time
import json
import re
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict
from collections import Counter

from dotenv import load_dotenv

# Load .env from current dir, parent dirs, or sibling dirs
for _candidate in [
    Path.cwd() / ".env",
    *Path.cwd().parent.glob("*/.env"),
]:
    if _candidate.is_file():
        load_dotenv(_candidate)
        break

S2_API_KEY_ENV = os.getenv("S2_API_KEY")


# ---- Data Classes ----

@dataclass
class AuthorMetrics:
    """Unified author metrics from any source."""
    source: str  # "semantic_scholar" or "google_scholar"
    name: str
    author_id: str
    url: str
    h_index: Optional[int] = None
    i10_index: Optional[int] = None  # GS only
    total_citations: Optional[int] = None
    paper_count: Optional[int] = None
    affiliations: Optional[List[str]] = None
    fields: Optional[List[str]] = None  # inferred or reported fields
    field_distribution: Optional[Dict[str, int]] = None  # field -> paper count
    # h-index variants
    h_index_last5y: Optional[int] = None  # GS "since" metric
    i10_index_last5y: Optional[int] = None
    citations_last5y: Optional[int] = None
    # Raw data for inspection
    raw: Optional[dict] = None


# ---- Semantic Scholar Fetcher ----

S2_BASE = "https://api.semanticscholar.org/graph/v1"

def _s2_get(endpoint: str, params: dict = None, api_key: str = None, retries: int = 4) -> dict:
    """Make a GET request to Semantic Scholar API with retry logic."""
    url = f"{S2_BASE}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {"Accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 3 * (attempt + 1)
                print(f"  [S2] Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                raise
    return {}


def search_semantic_scholar(
    name: str,
    api_key: str = None,
    max_candidates: int = 15,
    infer_fields: bool = True,
) -> List[AuthorMetrics]:
    if api_key is None:
        api_key = S2_API_KEY_ENV
    """
    Search for an author on Semantic Scholar and return candidate matches.

    Strategy:
    1. Search by name, retrieve top candidates with metrics.
    2. Sort by citationCount to surface the most likely "real" profile.
    3. For best candidates, fetch papers to infer primary field.

    Note on S2 fragmentation: A single real-world author may have multiple
    S2 profiles (e.g., "T. Tao" and "Terence Tao" as separate entries).
    We sort by citations and return the top match, but the --pick flag
    allows manual selection.
    """
    print(f"[S2] Searching for '{name}'...")
    data = _s2_get(
        "/author/search",
        params={
            "query": name,
            "fields": "name,hIndex,citationCount,paperCount,affiliations,url",
            "limit": max_candidates,
        },
        api_key=api_key,
    )

    if not data or "data" not in data:
        print("[S2] No results found.")
        return []

    candidates = []
    for author in data["data"]:
        metrics = AuthorMetrics(
            source="semantic_scholar",
            name=author.get("name", ""),
            author_id=author.get("authorId", ""),
            url=author.get("url", ""),
            h_index=author.get("hIndex"),
            total_citations=author.get("citationCount"),
            paper_count=author.get("paperCount"),
            affiliations=author.get("affiliations", []),
            raw=author,
        )
        candidates.append(metrics)

    # Sort by citation count descending — highest is most likely the "real" author
    candidates.sort(key=lambda x: x.total_citations or 0, reverse=True)

    print(f"  [S2] Found {len(candidates)} candidates. Top: {candidates[0].name} (h={candidates[0].h_index}, cit={candidates[0].total_citations})")

    # Infer fields for top candidate(s)
    if infer_fields and candidates:
        for c in candidates[:2]:  # top 2
            _s2_infer_fields(c, api_key)

    return candidates


def _s2_infer_fields(metrics: AuthorMetrics, api_key: str = None):
    """Fetch top papers for an author and infer their primary field(s)."""
    time.sleep(2)  # rate limit courtesy
    try:
        data = _s2_get(
            f"/author/{metrics.author_id}/papers",
            params={
                "fields": "fieldsOfStudy,s2FieldsOfStudy,citationCount",
                "limit": 100,
            },
            api_key=api_key,
        )
    except Exception as e:
        print(f"  [S2] Could not fetch papers for {metrics.name}: {e}")
        return

    if not data or "data" not in data:
        return

    field_counter = Counter()
    for paper in data["data"]:
        # Prefer s2FieldsOfStudy (richer), fall back to fieldsOfStudy
        fields = []
        if paper.get("s2FieldsOfStudy"):
            fields = [f["category"] for f in paper["s2FieldsOfStudy"]]
        elif paper.get("fieldsOfStudy"):
            fields = paper["fieldsOfStudy"]
        for f in fields:
            field_counter[f] += 1

    if field_counter:
        metrics.field_distribution = dict(field_counter.most_common())
        metrics.fields = [f for f, _ in field_counter.most_common(3)]
        print(f"  [S2] Field distribution for {metrics.name}: {dict(field_counter.most_common(5))}")


# ---- Google Scholar Fetcher ----

def search_google_scholar(
    name: str,
    max_candidates: int = 5,
    timeout_seconds: int = 30,
) -> List[AuthorMetrics]:
    """
    Search for an author on Google Scholar via the `scholarly` library.

    Returns candidates with h-index, i10-index, total citations,
    and interest tags (field labels).

    Falls back to a simpler approach if scholarly times out.
    """
    try:
        from scholarly import scholarly
    except ImportError:
        print("[GS] `scholarly` library not installed. Run: pip install scholarly")
        return []

    print(f"[GS] Searching for '{name}'...")
    candidates = []

    import signal

    class TimeoutError(Exception):
        pass

    def handler(signum, frame):
        raise TimeoutError("Google Scholar search timed out")

    # Set timeout
    old_handler = signal.signal(signal.SIGALRM, handler)
    signal.alarm(timeout_seconds)

    try:
        search_query = scholarly.search_author(name)
        for i, result in enumerate(search_query):
            if i >= max_candidates:
                break

            # Fill in full details
            try:
                author = scholarly.fill(result, sections=["basics", "indices", "counts"])
            except Exception as e:
                print(f"  [GS] Could not fill author details: {e}")
                author = result

            # Extract metrics
            metrics = AuthorMetrics(
                source="google_scholar",
                name=author.get("name", ""),
                author_id=author.get("scholar_id", ""),
                url=f"https://scholar.google.com/citations?user={author.get('scholar_id', '')}",
                h_index=author.get("hindex"),
                i10_index=author.get("i10index"),
                total_citations=author.get("citedby"),
                affiliations=[author.get("affiliation", "")] if author.get("affiliation") else [],
                fields=author.get("interests", []),
                raw={k: v for k, v in author.items() if k != "publications"},
            )

            # h-index last 5 years (GS "since" column)
            if "hindex5y" in author:
                metrics.h_index_last5y = author["hindex5y"]
            if "i10index5y" in author:
                metrics.i10_index_last5y = author["i10index5y"]
            if "citedby5y" in author:
                metrics.citations_last5y = author["citedby5y"]

            # Paper count from publications list
            if "publications" in author:
                metrics.paper_count = len(author["publications"])

            candidates.append(metrics)
            print(f"  [GS] Found: {metrics.name} (h={metrics.h_index}, i10={metrics.i10_index}, cit={metrics.total_citations})")

    except TimeoutError:
        print(f"[GS] Timed out after {timeout_seconds}s. Google Scholar may be rate-limiting.")
        print("[GS] Try again later, or use --s2-only, or set up a proxy.")
    except StopIteration:
        pass
    except Exception as e:
        print(f"[GS] Error searching: {e}")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

    return candidates


def parse_gs_profile_html(html: str, url: str = "") -> Optional[AuthorMetrics]:
    """
    Parse a Google Scholar profile page HTML to extract metrics.
    This is a fallback when the scholarly library fails.
    """
    metrics = AuthorMetrics(
        source="google_scholar",
        name="",
        author_id="",
        url=url,
    )

    # Extract name
    name_match = re.search(r'<div id="gsc_prf_in"[^>]*>([^<]+)</div>', html)
    if name_match:
        metrics.name = name_match.group(1).strip()

    # Extract affiliation
    aff_match = re.search(r'class="gsc_prf_ila"[^>]*>([^<]+)</a>', html)
    if aff_match:
        metrics.affiliations = [aff_match.group(1).strip()]

    # Extract interests
    interests = re.findall(r'class="gsc_prf_inta[^"]*"[^>]*>([^<]+)</a>', html)
    if interests:
        metrics.fields = [i.strip() for i in interests]

    # Extract citation metrics (gsc_rsb_std cells)
    # Order: citations-all, citations-since, h-index-all, h-index-since, i10-all, i10-since
    std_cells = re.findall(r'<td class="gsc_rsb_std">(\d+)</td>', html)
    if len(std_cells) >= 6:
        metrics.total_citations = int(std_cells[0])
        metrics.citations_last5y = int(std_cells[1])
        metrics.h_index = int(std_cells[2])
        metrics.h_index_last5y = int(std_cells[3])
        metrics.i10_index = int(std_cells[4])
        metrics.i10_index_last5y = int(std_cells[5])
    elif len(std_cells) >= 2:
        metrics.total_citations = int(std_cells[0])
        if len(std_cells) >= 4:
            metrics.h_index = int(std_cells[2])
        if len(std_cells) >= 6:
            metrics.i10_index = int(std_cells[4])

    # Extract scholar_id from URL
    id_match = re.search(r'user=([A-Za-z0-9_-]+)', url)
    if id_match:
        metrics.author_id = id_match.group(1)

    return metrics if metrics.name else None


# ---- Unified Search ----

def search_both(
    name: str,
    s2_api_key: str = None,
) -> Dict[str, List[AuthorMetrics]]:
    """
    Search both Semantic Scholar and Google Scholar for an author.
    Returns dict with keys "semantic_scholar" and "google_scholar".
    """
    results = {}

    # Semantic Scholar first (faster, more reliable)
    try:
        results["semantic_scholar"] = search_semantic_scholar(name, api_key=s2_api_key)
    except Exception as e:
        print(f"[S2] Error: {e}")
        results["semantic_scholar"] = []

    # Google Scholar (may be slow)
    try:
        results["google_scholar"] = search_google_scholar(name)
    except Exception as e:
        print(f"[GS] Error: {e}")
        results["google_scholar"] = []

    return results
