#!/usr/bin/env python3
"""
Citation Analyzer — "Pecking Order" Tool

Usage:
    python analyzer.py "Researcher Name" [--field "Mathematics"] [--s2-key YOUR_KEY]

Queries both Google Scholar and Semantic Scholar, infers the researcher's
primary field, and contextualizes their metrics against field-specific
percentile benchmarks.
"""

import sys
import argparse

from fetchers import search_semantic_scholar, search_google_scholar, AuthorMetrics
from ranker import rank_author, format_report
from benchmarks import FIELD_BENCHMARKS, match_field


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a researcher's citation metrics and rank them within their field."
    )
    parser.add_argument("name", help="Researcher name to look up")
    parser.add_argument(
        "--field", "-f",
        help="Override primary field (e.g., 'Mathematics', 'Computer Science')",
        default=None,
    )
    parser.add_argument(
        "--s2-key",
        help="Semantic Scholar API key for higher rate limits",
        default=None,
    )
    parser.add_argument(
        "--gs-only",
        help="Only query Google Scholar",
        action="store_true",
    )
    parser.add_argument(
        "--s2-only",
        help="Only query Semantic Scholar",
        action="store_true",
    )
    parser.add_argument(
        "--list-fields",
        help="List all available benchmark fields",
        action="store_true",
    )
    parser.add_argument(
        "--json",
        help="Output raw data as JSON",
        action="store_true",
    )
    parser.add_argument(
        "--pick",
        help="Interactively pick from candidate matches (default: auto-select best)",
        action="store_true",
    )

    args = parser.parse_args()

    if args.list_fields:
        print("Available benchmark fields:")
        print(f"  {'Field':<30} {'h-index median':>15} {'Citations median':>17}")
        print(f"  {'─' * 30} {'─' * 15} {'─' * 17}")
        for key, b in sorted(FIELD_BENCHMARKS.items()):
            print(f"  {b.field:<30} {b.h_p50:>15} {b.citation_p50:>17,}")
        return

    if not args.name:
        parser.print_help()
        return

    # Fetch from both sources
    s2_candidates = []
    gs_candidates = []

    if not args.gs_only:
        try:
            s2_candidates = search_semantic_scholar(args.name, api_key=args.s2_key)
        except Exception as e:
            print(f"[S2] Error: {e}")

    if not args.s2_only:
        try:
            gs_candidates = search_google_scholar(args.name)
        except Exception as e:
            print(f"[GS] Error: {e}")

    if not s2_candidates and not gs_candidates:
        print(f"\nNo results found for '{args.name}' on either platform.")
        print("Tips:")
        print("  - Try the full name as it appears on publications")
        print("  - Check spelling")
        print("  - Try with --s2-only or --gs-only to isolate issues")
        sys.exit(1)

    # Show candidates if --pick
    if args.pick:
        s2_candidates, gs_candidates = _interactive_pick(s2_candidates, gs_candidates)

    # Rank
    try:
        result = rank_author(s2_candidates, gs_candidates, preferred_field=args.field)
    except ValueError as e:
        print(f"\nError: {e}")
        sys.exit(1)

    # Output
    if args.json:
        import json
        data = {
            "name": result.name,
            "primary_field": result.primary_field,
            "h_index_best": result.h_index_best,
            "h_percentile_field": result.h_percentile,
            "h_percentile_general": result.h_percentile_general,
            "citation_count_best": result.citation_count_best,
            "citation_percentile_field": result.citation_percentile,
            "i10_index": result.i10_index,
            "paper_count": result.paper_count,
            "citations_per_paper": result.citations_per_paper,
            "field_normalized_citation_ratio": result.field_normalized_citation_ratio,
            "composite_score": result.composite_score,
            "overall_label": result.overall_label,
            "benchmark_field": result.benchmark.field,
            "sources": {
                "semantic_scholar": {
                    "url": result.s2.url if result.s2 else None,
                    "h_index": result.s2.h_index if result.s2 else None,
                    "citations": result.s2.total_citations if result.s2 else None,
                    "papers": result.s2.paper_count if result.s2 else None,
                },
                "google_scholar": {
                    "url": result.gs.url if result.gs else None,
                    "h_index": result.gs.h_index if result.gs else None,
                    "i10_index": result.gs.i10_index if result.gs else None,
                    "citations": result.gs.total_citations if result.gs else None,
                },
            },
        }
        print(json.dumps(data, indent=2))
    else:
        print(format_report(result))


def _interactive_pick(s2_candidates, gs_candidates):
    """Let user pick from candidate matches."""
    if s2_candidates:
        print("\n[Semantic Scholar Candidates]")
        for i, c in enumerate(s2_candidates[:10]):
            aff = f" ({', '.join(c.affiliations)})" if c.affiliations else ""
            fields = f" [{', '.join(c.fields)}]" if c.fields else ""
            print(f"  {i+1}. {c.name}{aff}{fields} — h={c.h_index}, cit={c.total_citations}, papers={c.paper_count}")
        try:
            pick = int(input("Pick S2 candidate (0 to skip): "))
            if 1 <= pick <= len(s2_candidates):
                s2_candidates = [s2_candidates[pick - 1]]
            elif pick == 0:
                s2_candidates = []
        except (ValueError, EOFError):
            pass

    if gs_candidates:
        print("\n[Google Scholar Candidates]")
        for i, c in enumerate(gs_candidates[:10]):
            aff = f" ({', '.join(c.affiliations)})" if c.affiliations else ""
            fields = f" [{', '.join(c.fields[:3])}]" if c.fields else ""
            print(f"  {i+1}. {c.name}{aff}{fields} — h={c.h_index}, i10={c.i10_index}, cit={c.total_citations}")
        try:
            pick = int(input("Pick GS candidate (0 to skip): "))
            if 1 <= pick <= len(gs_candidates):
                gs_candidates = [gs_candidates[pick - 1]]
            elif pick == 0:
                gs_candidates = []
        except (ValueError, EOFError):
            pass

    return s2_candidates, gs_candidates


if __name__ == "__main__":
    main()
