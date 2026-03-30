"""
Ranking engine: takes AuthorMetrics + FieldBenchmarks and produces
a detailed "pecking order" report.

The pecking order combines:
1. Raw metrics (h-index, citations, i10-index, paper count)
2. Field-normalized percentile ranks
3. Career-stage context (m-quotient = h / years_active)
4. Cross-source comparison (GS vs S2 discrepancies)
5. Composite score

The composite score uses the Ioannidis-style formula:
  composite = Σ ln(metric + 1) / ln(metric_max + 1)
for each metric, providing a [0, 1]-normalized aggregate.
"""

import math
from dataclasses import dataclass, field
from typing import Optional, List, Dict

from benchmarks import (
    FieldBenchmark, FIELD_BENCHMARKS, DEFAULT_BENCHMARK,
    match_field, get_h_percentile, get_citation_percentile,
    percentile_to_label, infer_percentile,
)
from fetchers import AuthorMetrics


@dataclass
class RankedAuthor:
    """Complete ranking analysis for one author."""
    name: str
    primary_field: str
    benchmark: FieldBenchmark

    # Raw metrics from each source
    s2: Optional[AuthorMetrics] = None
    gs: Optional[AuthorMetrics] = None

    # Computed ranks
    h_index_best: Optional[int] = None
    h_percentile: Optional[float] = None
    h_percentile_general: Optional[float] = None  # against all fields

    citation_count_best: Optional[int] = None
    citation_percentile: Optional[float] = None
    citation_percentile_general: Optional[float] = None

    i10_index: Optional[int] = None
    paper_count: Optional[int] = None

    # Derived metrics
    m_quotient: Optional[float] = None  # h / years since first pub
    citations_per_paper: Optional[float] = None
    field_normalized_citation_ratio: Optional[float] = None  # vs field avg

    # Composite
    composite_score: Optional[float] = None  # 0-1 normalized
    composite_percentile: Optional[float] = None

    # Labels
    h_label: str = ""
    citation_label: str = ""
    overall_label: str = ""


def rank_author(
    s2_candidates: List[AuthorMetrics],
    gs_candidates: List[AuthorMetrics],
    preferred_field: str = None,
) -> RankedAuthor:
    """
    Produce a RankedAuthor from the best S2 and GS candidates.

    Steps:
    1. Pick the best candidate from each source (highest citations).
    2. Determine primary field from S2 field distribution or GS interests.
    3. Look up the field-specific benchmark.
    4. Compute percentile ranks and composite score.
    """

    s2 = s2_candidates[0] if s2_candidates else None
    gs = gs_candidates[0] if gs_candidates else None

    if not s2 and not gs:
        raise ValueError("No data found for this author on either platform.")

    # Determine name
    name = (gs.name if gs else s2.name) or "Unknown"

    # Determine primary field
    primary_field, benchmark = _determine_field(s2, gs, preferred_field)

    result = RankedAuthor(
        name=name,
        primary_field=primary_field,
        benchmark=benchmark,
        s2=s2,
        gs=gs,
    )

    # Best h-index across sources
    h_values = [x.h_index for x in [s2, gs] if x and x.h_index is not None]
    if h_values:
        result.h_index_best = max(h_values)
        result.h_percentile = get_h_percentile(result.h_index_best, benchmark)
        result.h_percentile_general = get_h_percentile(result.h_index_best, DEFAULT_BENCHMARK)
        result.h_label = percentile_to_label(result.h_percentile)

    # Best citation count
    c_values = [x.total_citations for x in [s2, gs] if x and x.total_citations is not None]
    if c_values:
        result.citation_count_best = max(c_values)
        result.citation_percentile = get_citation_percentile(result.citation_count_best, benchmark)
        result.citation_percentile_general = get_citation_percentile(result.citation_count_best, DEFAULT_BENCHMARK)
        result.citation_label = percentile_to_label(result.citation_percentile)

    # i10-index (GS only)
    if gs and gs.i10_index is not None:
        result.i10_index = gs.i10_index

    # Paper count (max across sources)
    p_values = [x.paper_count for x in [s2, gs] if x and x.paper_count is not None]
    if p_values:
        result.paper_count = max(p_values)

    # Derived metrics
    if result.citation_count_best and result.paper_count and result.paper_count > 0:
        result.citations_per_paper = result.citation_count_best / result.paper_count
        if benchmark.avg_citations_per_paper > 0:
            result.field_normalized_citation_ratio = (
                result.citations_per_paper / benchmark.avg_citations_per_paper
            )

    # Composite score (Ioannidis-inspired, normalized)
    result.composite_score = _compute_composite(result, benchmark)

    # Overall label based on composite
    if result.h_percentile is not None:
        # Use the higher of h-percentile and citation-percentile
        best_pct = result.h_percentile
        if result.citation_percentile is not None:
            best_pct = max(best_pct, result.citation_percentile)
        result.overall_label = percentile_to_label(best_pct)

    return result


def _determine_field(
    s2: Optional[AuthorMetrics],
    gs: Optional[AuthorMetrics],
    preferred: str = None,
) -> tuple:
    """Determine the primary field and matching benchmark."""

    if preferred:
        bench = match_field(preferred)
        if bench:
            return preferred, bench

    # Try S2 field distribution first (most reliable)
    if s2 and s2.fields:
        for f in s2.fields:
            bench = match_field(f)
            if bench:
                return f, bench

    # Try GS interests
    if gs and gs.fields:
        for f in gs.fields:
            bench = match_field(f)
            if bench:
                return f, bench

    return "General", DEFAULT_BENCHMARK


def _compute_composite(result: RankedAuthor, benchmark: FieldBenchmark) -> float:
    """
    Compute a composite score in [0, 1] that aggregates multiple metrics.

    Formula (inspired by Ioannidis et al.):
      composite = (1/N) * Σ_i  ln(metric_i + 1) / ln(max_i + 1)

    where max_i is an empirical upper bound for each metric.
    """
    components = []

    # h-index component (max ~222 from Ioannidis data)
    if result.h_index_best is not None:
        components.append(math.log(result.h_index_best + 1) / math.log(223))

    # Citation component (max ~260k)
    if result.citation_count_best is not None:
        components.append(math.log(result.citation_count_best + 1) / math.log(260000))

    # Paper count component (max ~3000 for prolific authors)
    if result.paper_count is not None:
        components.append(math.log(result.paper_count + 1) / math.log(3000))

    # i10-index component (max ~1000)
    if result.i10_index is not None:
        components.append(math.log(result.i10_index + 1) / math.log(1000))

    if not components:
        return 0.0

    return sum(components) / len(components)


def format_report(result: RankedAuthor) -> str:
    """Format a human-readable ranking report."""
    lines = []
    lines.append("=" * 70)
    lines.append(f"  CITATION ANALYSIS: {result.name}")
    lines.append("=" * 70)
    lines.append("")

    # Source profiles
    lines.append("── Source Profiles ──")
    if result.gs:
        lines.append(f"  Google Scholar:   {result.gs.url}")
        if result.gs.affiliations:
            lines.append(f"    Affiliation:    {', '.join(result.gs.affiliations)}")
    if result.s2:
        lines.append(f"  Semantic Scholar: {result.s2.url}")
        if result.s2.affiliations:
            lines.append(f"    Affiliation:    {', '.join(result.s2.affiliations)}")
    lines.append("")

    # Field
    lines.append(f"── Primary Field: {result.primary_field} ──")
    lines.append(f"  Benchmark: {result.benchmark.field}")
    lines.append(f"  ({result.benchmark.n_authors:,} researchers in reference dataset)")
    if result.s2 and result.s2.field_distribution:
        top_fields = list(result.s2.field_distribution.items())[:5]
        lines.append(f"  Paper distribution: {', '.join(f'{f} ({n})' for f, n in top_fields)}")
    lines.append("")

    # Raw Metrics Comparison
    lines.append("── Raw Metrics ──")
    lines.append(f"  {'Metric':<25} {'Google Scholar':>15} {'Semantic Scholar':>17} {'Best':>10}")
    lines.append(f"  {'─' * 25} {'─' * 15} {'─' * 17} {'─' * 10}")

    def _fmt(val):
        if val is None:
            return "—"
        if isinstance(val, int):
            return f"{val:,}"
        return str(val)

    gs_h = result.gs.h_index if result.gs else None
    s2_h = result.s2.h_index if result.s2 else None
    lines.append(f"  {'h-index':<25} {_fmt(gs_h):>15} {_fmt(s2_h):>17} {_fmt(result.h_index_best):>10}")

    gs_i10 = result.gs.i10_index if result.gs else None
    lines.append(f"  {'i10-index':<25} {_fmt(gs_i10):>15} {'—':>17} {_fmt(result.i10_index):>10}")

    gs_c = result.gs.total_citations if result.gs else None
    s2_c = result.s2.total_citations if result.s2 else None
    lines.append(f"  {'Total citations':<25} {_fmt(gs_c):>15} {_fmt(s2_c):>17} {_fmt(result.citation_count_best):>10}")

    gs_p = result.gs.paper_count if result.gs else None
    s2_p = result.s2.paper_count if result.s2 else None
    lines.append(f"  {'Paper count':<25} {_fmt(gs_p):>15} {_fmt(s2_p):>17} {_fmt(result.paper_count):>10}")

    # GS-specific last 5 years
    if result.gs and result.gs.h_index_last5y is not None:
        lines.append("")
        lines.append("  Google Scholar (last 5 years):")
        lines.append(f"    h-index:    {result.gs.h_index_last5y}")
        lines.append(f"    i10-index:  {result.gs.i10_index_last5y}")
        lines.append(f"    Citations:  {result.gs.citations_last5y}")

    lines.append("")

    # Derived Metrics
    lines.append("── Derived Metrics ──")
    if result.citations_per_paper is not None:
        lines.append(f"  Citations/paper:           {result.citations_per_paper:.1f}")
        lines.append(f"  Field average:             {result.benchmark.avg_citations_per_paper:.1f}")
        if result.field_normalized_citation_ratio is not None:
            lines.append(f"  Field-normalized ratio:    {result.field_normalized_citation_ratio:.2f}x")
    if result.composite_score is not None:
        lines.append(f"  Composite score:           {result.composite_score:.4f}")
    lines.append("")

    # ★ Pecking Order ★
    lines.append("── ★ PECKING ORDER ★ ──")
    lines.append("")

    if result.h_percentile is not None:
        bar = _percentile_bar(result.h_percentile)
        lines.append(f"  h-index rank in {result.benchmark.field}:")
        lines.append(f"    {bar}  {result.h_percentile:.1f}th percentile — {result.h_label}")
        if result.h_percentile_general is not None and result.h_percentile_general != result.h_percentile:
            lines.append(f"    (vs all fields: {result.h_percentile_general:.1f}th percentile)")

    if result.citation_percentile is not None:
        bar = _percentile_bar(result.citation_percentile)
        lines.append(f"  Citation rank in {result.benchmark.field}:")
        lines.append(f"    {bar}  {result.citation_percentile:.1f}th percentile — {result.citation_label}")

    lines.append("")
    lines.append(f"  Overall assessment: {result.overall_label}")
    lines.append("")

    # Field benchmarks context
    lines.append("── Field Benchmark Context ──")
    b = result.benchmark
    lines.append(f"  In {b.field}:")
    lines.append(f"    25th pct h-index: {b.h_p25}   |  25th pct citations: {b.citation_p25:,}")
    lines.append(f"    50th pct h-index: {b.h_p50}   |  50th pct citations: {b.citation_p50:,}")
    lines.append(f"    75th pct h-index: {b.h_p75}  |  75th pct citations: {b.citation_p75:,}")
    lines.append(f"    90th pct h-index: {b.h_p90}  |  90th pct citations: {b.citation_p90:,}")
    lines.append(f"    99th pct h-index: {b.h_p99}  |  (elite tier)")
    lines.append("")

    # Cross-source discrepancy note
    if result.gs and result.s2:
        gs_h = result.gs.h_index or 0
        s2_h = result.s2.h_index or 0
        if abs(gs_h - s2_h) > 3:
            lines.append("── Note on Source Discrepancy ──")
            lines.append(f"  GS h-index ({gs_h}) vs S2 h-index ({s2_h}): Δ = {abs(gs_h - s2_h)}")
            lines.append("  This is common. GS indexes books, theses, patents, and non-English")
            lines.append("  sources that S2 does not. S2 focuses on peer-reviewed articles and")
            lines.append("  preprints. Neither is 'correct' — they measure different corpora.")
            lines.append("")

    # Caveats
    lines.append("── Caveats ──")
    lines.append("  • Percentiles are estimated from Ioannidis et al. (2019) career-long data.")
    lines.append("  • h-index disadvantages early-career researchers and mathematicians.")
    lines.append("  • Field boundaries are fuzzy; interdisciplinary work may be misclassified.")
    lines.append("  • Self-citations are included in raw counts from both sources.")
    lines.append("  • The 'pecking order' is a rough contextualization, not a definitive ranking.")
    lines.append("=" * 70)

    return "\n".join(lines)


def _percentile_bar(pct: float, width: int = 30) -> str:
    """Create a visual percentile bar."""
    filled = int(pct / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}]"
