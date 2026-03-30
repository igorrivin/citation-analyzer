"""
OpenAlex fetcher — the best data source for sub-field benchmarking.

OpenAlex provides:
  - Author search with h-index, i10-index, cited_by_count, works_count
  - ~4,500 research topics organized into 254 subfields → 26 fields → 4 domains
  - group_by queries to compute h-index distributions per topic/subfield
  - Free, no API key required (polite pool with mailto)

This module handles:
  1. Author lookup with topic/subfield identification
  2. Live computation of sub-field percentile benchmarks via group_by
  3. Career-stage estimation from first publication year
  4. Per-topic h-index decomposition (for generalists)
  5. Citation distribution shape analysis (L∞, Gini, concentration)
"""

import json
import time
import math
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from collections import Counter, defaultdict


OPENALEX_BASE = "https://api.openalex.org"
# Polite pool: include mailto for faster rate limits
MAILTO = "citation-analyzer@example.com"


@dataclass
class OpenAlexAuthor:
    """Author data from OpenAlex."""
    openalex_id: str
    name: str
    h_index: int
    i10_index: int
    cited_by_count: int
    works_count: int
    topics: List[Dict]  # [{display_name, id, subfield, field, domain}, ...]
    primary_topic: Optional[Dict] = None
    affiliations: Optional[List[str]] = None
    first_pub_year: Optional[int] = None
    last_pub_year: Optional[int] = None
    counts_by_year: Optional[List[Dict]] = None
    url: str = ""
    orcid: Optional[str] = None


@dataclass
class SubfieldBenchmark:
    """Empirical h-index distribution for a specific subfield/topic."""
    name: str
    topic_id: str
    total_authors: int
    # CDF: list of (h_value, cumulative_count) pairs
    cdf: List[Tuple[int, int]]
    # Pre-computed percentiles
    p25_h: int = 0
    p50_h: int = 0
    p75_h: int = 0
    p90_h: int = 0
    p95_h: int = 0
    p99_h: int = 0


def _oa_get(endpoint: str, params: dict = None, retries: int = 3) -> dict:
    """Make a GET request to OpenAlex API."""
    url = f"{OPENALEX_BASE}{endpoint}"
    if params is None:
        params = {}
    params["mailto"] = MAILTO
    url += "?" + urllib.parse.urlencode(params)

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 * (attempt + 1)
                print(f"  [OA] Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                raise
    return {}


# ============================================================
# Author Search
# ============================================================

def search_openalex_author(name: str, max_results: int = 10) -> List[OpenAlexAuthor]:
    """Search for an author by name on OpenAlex."""
    print(f"[OA] Searching for '{name}'...")
    data = _oa_get("/authors", params={
        "search": name,
        "per_page": max_results,
    })

    if not data or "results" not in data:
        print("[OA] No results found.")
        return []

    candidates = []
    for r in data["results"]:
        stats = r.get("summary_stats", {})
        topics = r.get("topics", [])

        # Determine first/last publication year from counts_by_year
        counts_by_year = r.get("counts_by_year", [])
        first_year = None
        last_year = None
        if counts_by_year:
            years = [c["year"] for c in counts_by_year if c.get("works_count", 0) > 0]
            if years:
                first_year = min(years)
                last_year = max(years)

        # Affiliations
        affiliations = []
        for inst in r.get("last_known_institutions", []) or []:
            if inst.get("display_name"):
                affiliations.append(inst["display_name"])

        author = OpenAlexAuthor(
            openalex_id=r.get("id", ""),
            name=r.get("display_name", ""),
            h_index=stats.get("h_index", 0),
            i10_index=stats.get("i10_index", 0),
            cited_by_count=r.get("cited_by_count", 0),
            works_count=r.get("works_count", 0),
            topics=[{
                "display_name": t.get("display_name", ""),
                "id": t.get("id", ""),
                "subfield": t.get("subfield", {}).get("display_name", "") if t.get("subfield") else "",
                "field": t.get("field", {}).get("display_name", "") if t.get("field") else "",
                "domain": t.get("domain", {}).get("display_name", "") if t.get("domain") else "",
            } for t in topics],
            affiliations=affiliations,
            first_pub_year=first_year,
            last_pub_year=last_year,
            counts_by_year=counts_by_year,
            url=r.get("id", "").replace("https://openalex.org/", "https://openalex.org/authors/"),
            orcid=r.get("orcid"),
        )
        candidates.append(author)

    # Sort by cited_by_count descending
    candidates.sort(key=lambda x: x.cited_by_count, reverse=True)

    if candidates:
        top = candidates[0]
        top_topics = [t["display_name"] for t in top.topics[:3]]
        print(f"  [OA] Top match: {top.name} (h={top.h_index}, cit={top.cited_by_count:,}, topics: {top_topics})")

    return candidates


# ============================================================
# Live Sub-field Benchmark (via group_by)
# ============================================================

def compute_subfield_benchmark(topic_id: str, topic_name: str = "") -> Optional[SubfieldBenchmark]:
    """
    Compute the h-index distribution for all authors tagged with a given
    OpenAlex topic, using the group_by API.

    This gives us a real, empirical CDF — no approximations.
    """
    if not topic_id.startswith("http"):
        topic_id_param = topic_id
    else:
        topic_id_param = topic_id.split("/")[-1]

    print(f"  [OA] Computing benchmark for topic {topic_name or topic_id_param}...")

    data = _oa_get("/authors", params={
        "filter": f"topics.id:{topic_id_param}",
        "group_by": "summary_stats.h_index",
        "per_page": "200",
    })

    if not data or "group_by" not in data:
        print(f"  [OA] Could not compute benchmark for {topic_id_param}")
        return None

    groups = data["group_by"]
    total = sum(g["count"] for g in groups)

    if total == 0:
        return None

    # Build sorted CDF
    sorted_groups = sorted(groups, key=lambda x: int(x["key"]))
    cdf = []
    cumulative = 0
    for g in sorted_groups:
        cumulative += g["count"]
        cdf.append((int(g["key"]), cumulative))

    def _percentile_h(target_pct):
        target_count = total * target_pct / 100.0
        for h_val, cum in cdf:
            if cum >= target_count:
                return h_val
        return cdf[-1][0] if cdf else 0

    bench = SubfieldBenchmark(
        name=topic_name or topic_id_param,
        topic_id=topic_id_param,
        total_authors=total,
        cdf=cdf,
        p25_h=_percentile_h(25),
        p50_h=_percentile_h(50),
        p75_h=_percentile_h(75),
        p90_h=_percentile_h(90),
        p95_h=_percentile_h(95),
        p99_h=_percentile_h(99),
    )

    print(f"  [OA] {topic_name}: {total:,} authors | median h={bench.p50_h}, p90={bench.p90_h}, p99={bench.p99_h}")
    return bench


def get_exact_percentile(h_index: int, benchmark: SubfieldBenchmark) -> float:
    """Get exact percentile rank using the empirical CDF."""
    if not benchmark.cdf or benchmark.total_authors == 0:
        return 0.0
    cumulative = 0
    for h_val, cum in benchmark.cdf:
        if h_val <= h_index:
            cumulative = cum
        else:
            break
    return (cumulative / benchmark.total_authors) * 100.0


# ============================================================
# Career-Stage Metrics
# ============================================================

def compute_career_metrics(author: OpenAlexAuthor) -> Dict:
    """
    Compute career-stage-adjusted metrics:
    - years_active, m-quotient, annual citation rate, productivity
    - recent momentum (fraction of citations in last 3 years)
    """
    result = {}
    if author.first_pub_year:
        import datetime
        current_year = datetime.datetime.now().year
        years = max(1, current_year - author.first_pub_year)
        result["years_active"] = years
        result["first_pub_year"] = author.first_pub_year
        result["m_quotient"] = author.h_index / years
        result["annual_citation_rate"] = author.cited_by_count / years
        result["productivity"] = author.works_count / years

        if author.counts_by_year and author.cited_by_count > 0:
            recent_cites = sum(
                c.get("cited_by_count", 0)
                for c in author.counts_by_year
                if c["year"] >= current_year - 3
            )
            result["recent_momentum"] = recent_cites / author.cited_by_count
            result["recent_citations_3yr"] = recent_cites
    else:
        result["years_active"] = None
    return result


# ============================================================
# Per-Topic h-index Decomposition + Distribution Shape
# ============================================================

def fetch_all_works(author_id: str) -> List[Dict]:
    """Fetch all works for an author with citation counts and topic assignments."""
    # Accept full URL or bare ID
    if "/" in author_id:
        author_id = author_id.split("/")[-1]

    works = []
    page = 1
    while True:
        wdata = _oa_get("/works", params={
            "filter": f"authorships.author.id:{author_id}",
            "select": "title,cited_by_count,primary_topic,publication_year",
            "per_page": "100",
            "page": str(page),
            "sort": "cited_by_count:desc",
        })
        results = wdata.get("results", [])
        if not results:
            break
        works.extend(results)
        page += 1
        time.sleep(0.3)
    return works


def compute_per_topic_h(works: List[Dict]) -> List[Tuple[str, Dict]]:
    """
    Decompose an author's works by OpenAlex primary_topic, computing
    per-topic h-index, paper count, total citations, and c_max.

    Returns list of (topic_name, stats_dict) sorted by h descending.
    """
    topic_papers = defaultdict(list)
    topic_meta = {}

    for w in works:
        pt = w.get("primary_topic")
        if pt:
            tname = pt["display_name"]
            topic_papers[tname].append(w.get("cited_by_count", 0))
            if tname not in topic_meta:
                topic_meta[tname] = {
                    "id": pt["id"].split("/")[-1] if "/" in pt.get("id", "") else pt.get("id", ""),
                    "subfield": pt.get("subfield", {}).get("display_name", "") if pt.get("subfield") else "",
                    "field": pt.get("field", {}).get("display_name", "") if pt.get("field") else "",
                }

    result = []
    for tname, cites_list in topic_papers.items():
        sorted_c = sorted(cites_list, reverse=True)
        h = 0
        for i, c in enumerate(sorted_c):
            if c >= i + 1:
                h = i + 1
            else:
                break
        result.append((tname, {
            "h": h,
            "n_papers": len(cites_list),
            "total_cites": sum(cites_list),
            "max_cite": max(cites_list),
            "topic_id": topic_meta.get(tname, {}).get("id", ""),
            "subfield": topic_meta.get(tname, {}).get("subfield", ""),
            "field": topic_meta.get(tname, {}).get("field", ""),
        }))

    result.sort(key=lambda x: (-x[1]["h"], -x[1]["total_cites"]))
    return result


def compute_distribution_shape(works: List[Dict]) -> Dict:
    """
    Analyze the shape of the citation distribution:
    - L∞ (c_max) and top-k values
    - Gini coefficient
    - Concentration ratios (top-1, top-5, top-10 share)
    - c_max/c_2 ratio (spikiness)
    - c_max/h² ratio (peak vs breadth)
    - Top paper details
    """
    cc = sorted([w.get("cited_by_count", 0) for w in works], reverse=True)
    n = len(cc)
    total_c = sum(cc)

    c_max = cc[0] if n > 0 else 0
    c_2 = cc[1] if n > 1 else 0
    c_5 = cc[4] if n > 4 else 0
    c_10 = cc[9] if n > 9 else 0

    top_paper = max(works, key=lambda w: w.get("cited_by_count", 0)) if works else None

    # Gini coefficient
    if n > 0 and total_c > 0:
        sa = sorted(cc)
        cs = sum((i + 1) * sa[i] for i in range(n))
        gini = (2 * cs) / (n * sum(sa)) - (n + 1) / n
    else:
        gini = 0

    return {
        "c_max": c_max,
        "c_2": c_2,
        "c_5": c_5,
        "c_10": c_10,
        "c_max_over_c2": c_max / max(c_2, 1),
        "gini": gini,
        "top1_share": c_max / total_c if total_c > 0 else 0,
        "top5_share": sum(cc[:5]) / total_c if total_c > 0 else 0,
        "top10_share": sum(cc[:10]) / total_c if total_c > 0 else 0,
        "total_citations_from_works": total_c,
        "n_works": n,
        "top_paper": top_paper,
        "citation_counts": cc,
    }


def compute_breadth_metrics(works: List[Dict]) -> Dict:
    """
    Measure research breadth using information-theoretic metrics:
    - Number of unique topics and subfields
    - Shannon entropy of topic distribution (normalized)
    - Effective number of topics (1/HHI)
    - Top-topic concentration
    """
    topic_counter = Counter()
    subfield_counter = Counter()

    for w in works:
        pt = w.get("primary_topic")
        if pt:
            topic_counter[pt["display_name"]] += 1
            sf = pt.get("subfield", {}).get("display_name", "") if pt.get("subfield") else ""
            if sf:
                subfield_counter[sf] += 1

    total = sum(topic_counter.values())
    n_topics = len(topic_counter)
    n_subfields = len(subfield_counter)

    if total > 0 and n_topics > 1:
        probs = [c / total for c in topic_counter.values()]
        entropy = -sum(p * math.log2(p) for p in probs if p > 0)
        max_entropy = math.log2(n_topics)
        normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0

        hhi = sum((c / total) ** 2 for c in topic_counter.values())
        effective_topics = 1.0 / hhi if hhi > 0 else 0

        top_topic_share = max(topic_counter.values()) / total
    else:
        entropy = 0
        normalized_entropy = 0
        effective_topics = 1
        top_topic_share = 1

    return {
        "n_topics": n_topics,
        "n_subfields": n_subfields,
        "entropy_bits": entropy,
        "normalized_entropy": normalized_entropy,
        "effective_topics": effective_topics,
        "top_topic_share": top_topic_share,
        "topic_distribution": topic_counter.most_common(),
        "subfield_distribution": subfield_counter.most_common(),
    }


# ============================================================
# Full Analysis Pipeline
# ============================================================

def full_analysis(
    name: str,
    preferred_topic: str = None,
    benchmark_top_n: int = 3,
    author: "OpenAlexAuthor" = None,
) -> Dict:
    """
    Complete analysis pipeline:
    1. Search for author on OpenAlex (or use pre-selected author)
    2. Fetch all their works
    3. Compute per-topic h-index decomposition
    4. Compute citation distribution shape (L∞, Gini, etc.)
    5. Compute breadth metrics (entropy, effective topics)
    6. Compute live sub-field benchmarks for top topics
    7. Compute career-stage metrics

    Returns a dict with all analysis results.
    """
    if author is None:
        candidates = search_openalex_author(name)
        if not candidates:
            return {"error": f"No results found for '{name}'"}
        author = candidates[0]
    else:
        candidates = [author]
    aid = author.openalex_id.split("/")[-1]

    # Fetch all works
    print(f"  [OA] Fetching works for {author.name}...")
    works = fetch_all_works(aid)
    print(f"  [OA] Fetched {len(works)} works.")

    # Per-topic h-index
    per_topic = compute_per_topic_h(works)

    # Distribution shape
    shape = compute_distribution_shape(works)

    # Breadth
    breadth = compute_breadth_metrics(works)

    # Career metrics
    career = compute_career_metrics(author)

    # c_max / h² ratio
    if author.h_index > 0:
        shape["c_max_over_h2"] = shape["c_max"] / (author.h_index ** 2)
    else:
        shape["c_max_over_h2"] = 0

    # Determine which topics to benchmark
    benchmark_topics = []
    if preferred_topic:
        topic_data = _oa_get("/topics", params={"search": preferred_topic, "per_page": 5})
        if topic_data and topic_data.get("results"):
            t = topic_data["results"][0]
            benchmark_topics.append({
                "id": t["id"].split("/")[-1],
                "name": t["display_name"],
            })

    if not benchmark_topics:
        for tname, tdata in per_topic[:benchmark_top_n]:
            if tdata["topic_id"]:
                benchmark_topics.append({"id": tdata["topic_id"], "name": tname})

    # Build lookup from topic name to per-topic h-index
    per_topic_h_map = {tname: tdata["h"] for tname, tdata in per_topic}

    # Compute benchmarks using per-topic h-index, not global h-index
    benchmarks = {}
    rankings = {}
    for bt in benchmark_topics:
        time.sleep(0.3)
        bench = compute_subfield_benchmark(bt["id"], bt["name"])
        if bench:
            benchmarks[bt["name"]] = bench
            topic_h = per_topic_h_map.get(bt["name"], author.h_index)
            pct = get_exact_percentile(topic_h, bench)
            rankings[bt["name"]] = {
                "topic_h": topic_h,
                "h_percentile": pct,
                "total_authors": bench.total_authors,
                "median_h": bench.p50_h,
                "p90_h": bench.p90_h,
                "p99_h": bench.p99_h,
            }

    return {
        "author": author,
        "works": works,
        "per_topic": per_topic,
        "shape": shape,
        "breadth": breadth,
        "career": career,
        "benchmarks": benchmarks,
        "rankings": rankings,
        "candidates": candidates,
    }


# ============================================================
# Report Formatter
# ============================================================

def format_full_report(analysis: Dict) -> str:
    """Format the complete analysis as a human-readable report."""
    if "error" in analysis:
        return f"Error: {analysis['error']}"

    author = analysis["author"]
    shape = analysis["shape"]
    breadth = analysis["breadth"]
    career = analysis["career"]
    per_topic = analysis["per_topic"]
    rankings = analysis["rankings"]

    L = []
    L.append("=" * 76)
    L.append(f"  FULL CITATION PROFILE: {author.name}")
    L.append(f"  (via OpenAlex — empirical sub-field benchmarks)")
    L.append("=" * 76)

    # ── Profile ──
    L.append("\n── Profile ──")
    oa_url = author.openalex_id.replace("https://openalex.org/", "https://openalex.org/authors/")
    L.append(f"  OpenAlex:      {oa_url}")
    if author.orcid:
        L.append(f"  ORCID:         {author.orcid}")
    if author.affiliations:
        L.append(f"  Affiliations:  {', '.join(author.affiliations)}")

    # ── Global Metrics ──
    L.append("\n── Global Metrics ──")
    L.append(f"  h-index:           {author.h_index}")
    L.append(f"  i10-index:         {author.i10_index}")
    L.append(f"  Total citations:   {author.cited_by_count:,}")
    L.append(f"  Total works:       {author.works_count}")
    if author.works_count > 0:
        L.append(f"  Citations/paper:   {author.cited_by_count / author.works_count:.1f}")

    # ── L∞ (Peak Impact) ──
    L.append("\n── L∞ (Peak Impact) ──")
    tp = shape.get("top_paper")
    if tp:
        title = tp.get("title", "?")[:72]
        L.append(f"  Top paper: \"{title}\"")
        L.append(f"    {tp.get('cited_by_count', 0):,} citations ({tp.get('publication_year', '?')})")
    L.append(f"  c_max:         {shape['c_max']:>8,}  (top paper)")
    L.append(f"  c_2:           {shape['c_2']:>8,}  (2nd highest)")
    L.append(f"  c_5:           {shape['c_5']:>8,}  (5th highest)")
    L.append(f"  c_10:          {shape['c_10']:>8,}  (10th highest)")
    L.append(f"  c_max / c_2:   {shape['c_max_over_c2']:>8.1f}x  (spikiness)")
    L.append(f"  c_max / h²:    {shape.get('c_max_over_h2', 0):>8.1f}   (peak vs breadth)")

    # ── Distribution Shape ──
    L.append("\n── Citation Distribution Shape ──")
    L.append(f"  Gini coefficient:    {shape['gini']:.3f}  (0=equal, 1=one paper has all)")
    L.append(f"  Top-1 paper share:   {shape['top1_share']:.1%} of all citations")
    L.append(f"  Top-5 papers share:  {shape['top5_share']:.1%}")
    L.append(f"  Top-10 papers share: {shape['top10_share']:.1%}")

    # ── Research Breadth ──
    L.append("\n── Research Breadth ──")
    L.append(f"  Unique topics:       {breadth['n_topics']}")
    L.append(f"  Unique subfields:    {breadth['n_subfields']}")
    L.append(f"  Effective topics:    {breadth['effective_topics']:.1f}  (1/HHI)")
    L.append(f"  Normalized entropy:  {breadth['normalized_entropy']:.2f}  (1.0 = perfectly uniform)")
    L.append(f"  Top-topic share:     {breadth['top_topic_share']:.1%}")

    # Top subfields
    if breadth["subfield_distribution"]:
        L.append("  Subfield breakdown:")
        for sf, count in breadth["subfield_distribution"][:8]:
            L.append(f"    {sf:<45} {count:>3} papers")

    # ── Career Stage ──
    if career.get("years_active"):
        L.append("\n── Career Stage ──")
        L.append(f"  First publication: {career['first_pub_year']}")
        L.append(f"  Years active:      {career['years_active']}")
        L.append(f"  m-quotient (h/yr): {career['m_quotient']:.2f}")
        L.append(f"  Papers/year:       {career['productivity']:.1f}")
        L.append(f"  Citations/year:    {career['annual_citation_rate']:.1f}")
        if "recent_momentum" in career:
            L.append(f"  Recent momentum:   {career['recent_momentum']:.1%} of citations in last 3 years")

        yrs = career["years_active"]
        if yrs <= 7:
            stage = "Early career (≤7 years)"
        elif yrs <= 15:
            stage = "Mid career (8-15 years)"
        elif yrs <= 25:
            stage = "Established (16-25 years)"
        else:
            stage = f"Senior ({yrs} years)"
        L.append(f"  Career stage:      {stage}")

        mq = career["m_quotient"]
        if mq >= 2.0:
            mq_label = "Outstanding (m ≥ 2)"
        elif mq >= 1.0:
            mq_label = "Very good (m ≥ 1)"
        elif mq >= 0.5:
            mq_label = "Good (m ≥ 0.5)"
        else:
            mq_label = "Below typical"
        L.append(f"  m-quotient rating: {mq_label}")

    # ── Per-Topic h-index Decomposition ──
    L.append(f"\n── Per-Topic h-index Decomposition ({breadth['n_topics']} topics) ──")
    L.append(f"  {'Topic':<50} {'Papers':>6} {'h':>3} {'Cites':>7} {'c_max':>6}")
    L.append(f"  {'-'*50} {'-'*6} {'-'*3} {'-'*7} {'-'*6}")
    for tname, d in per_topic[:20]:
        label = tname[:48] if len(tname) <= 48 else tname[:47] + "…"
        L.append(f"  {label:<50} {d['n_papers']:>6} {d['h']:>3} {d['total_cites']:>7,} {d['max_cite']:>6,}")

    remaining = per_topic[20:]
    if remaining:
        rem_p = sum(d["n_papers"] for _, d in remaining)
        rem_c = sum(d["total_cites"] for _, d in remaining)
        L.append(f"  {'... + ' + str(len(remaining)) + ' more topics':<50} {rem_p:>6} {'':>3} {rem_c:>7,}")

    # ── Sub-field Pecking Order ──
    if rankings:
        L.append(f"\n── ★ SUB-FIELD PECKING ORDER ★ ──")
        L.append(f"  (using per-topic h-index, not global h={author.h_index})")
        L.append("")

        for topic_name, rank in rankings.items():
            pct = rank["h_percentile"]
            topic_h = rank.get("topic_h", author.h_index)
            n = rank["total_authors"]
            bar = _pct_bar(pct)

            if pct >= 99:     label = "Top 1% (Elite)"
            elif pct >= 95:   label = "Top 5% (Exceptional)"
            elif pct >= 90:   label = "Top 10% (Outstanding)"
            elif pct >= 75:   label = "Top 25% (Very Good)"
            elif pct >= 50:   label = "Above Median"
            elif pct >= 25:   label = "Below Median"
            else:             label = "Bottom Quartile"

            L.append(f"  In '{topic_name}' ({n:,} authors, topic h={topic_h}):")
            L.append(f"    {bar}  {pct:.1f}th pct — {label}")
            L.append(f"    median h={rank['median_h']}, p90={rank['p90_h']}, p99={rank['p99_h']}")
            L.append("")

    # ── Caveats ──
    L.append("── Caveats ──")
    L.append("  • Benchmarks are computed live from OpenAlex's full author database.")
    L.append("  • Includes all authors tagged with a topic (at any career stage).")
    L.append("  • ~30% of authors in any topic have h=0 (single publication, etc.).")
    L.append("  • The m-quotient (h/years) partially corrects for career stage but")
    L.append("    assumes linear h growth, which is empirically concave.")
    L.append("  • For generalists, the per-topic h decomposition is more informative")
    L.append("    than the global h-index benchmarked against any single field.")
    L.append("  • OpenAlex author disambiguation is imperfect; verify the profile URL.")
    L.append("=" * 76)

    return "\n".join(L)


def _pct_bar(pct: float, width: int = 30) -> str:
    filled = int(pct / 100 * width)
    return f"[{'█' * filled}{'░' * (width - filled)}]"


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(
        description="Full citation profile with sub-field benchmarks, distribution shape, and breadth analysis."
    )
    parser.add_argument("name", help="Researcher name to look up")
    parser.add_argument("--topic", "-t", help="Override primary topic for benchmarking", default=None)
    parser.add_argument("--benchmarks", "-b", type=int, default=3,
                        help="Number of top topics to benchmark (default: 3)")
    parser.add_argument("--json", action="store_true", help="Output raw data as JSON")

    args = parser.parse_args()

    analysis = full_analysis(args.name, preferred_topic=args.topic, benchmark_top_n=args.benchmarks)

    if args.json:
        # Serialize (strip non-serializable objects)
        import json as jsonmod
        out = {
            "name": analysis["author"].name,
            "h_index": analysis["author"].h_index,
            "i10_index": analysis["author"].i10_index,
            "cited_by_count": analysis["author"].cited_by_count,
            "works_count": analysis["author"].works_count,
            "shape": {k: v for k, v in analysis["shape"].items()
                      if k not in ("top_paper", "citation_counts")},
            "breadth": {k: v for k, v in analysis["breadth"].items()
                        if k not in ("topic_distribution", "subfield_distribution")},
            "career": analysis["career"],
            "per_topic_h": [
                {"topic": t, "h": d["h"], "papers": d["n_papers"],
                 "citations": d["total_cites"], "c_max": d["max_cite"]}
                for t, d in analysis["per_topic"][:30]
            ],
            "rankings": analysis["rankings"],
        }
        print(jsonmod.dumps(out, indent=2))
    else:
        print(format_full_report(analysis))
