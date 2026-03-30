"""
Field-specific citation benchmarks for contextualizing researcher metrics.

Data sources:
- Ioannidis et al. (2019) "A standardized citation metrics author database" (PLoS Biology)
  Career-long percentiles for 22 fields, 6.88M scientists.
  https://pmc.ncbi.nlm.nih.gov/articles/PMC6699798/
- Samwell.ai h-index ranges by discipline (compiled from multiple studies)
  https://www.samwell.ai/blog/what-is-a-good-h-index
- Iglesias & Pecharromán (2007) "Comparison of the h-index for Different Fields"
  https://arxiv.org/pdf/1708.07893

The benchmarks below encode percentile-based h-index distributions per field.
These are approximate and meant for contextual ranking, not definitive evaluation.
"""

from dataclasses import dataclass
from typing import Optional

@dataclass
class FieldBenchmark:
    """Benchmark h-index and citation data for a single academic field."""
    field: str
    # Total citation percentiles (career-long, from Ioannidis 2019)
    citation_p25: int
    citation_p50: int  # median
    citation_p75: int
    citation_p90: int
    # h-index percentile estimates (compiled from multiple sources)
    h_p25: int   # 25th percentile h-index
    h_p50: int   # median h-index
    h_p75: int   # 75th percentile h-index
    h_p90: int   # 90th percentile h-index
    h_p99: int   # 99th percentile (elite)
    # Typical number of researchers in field (Ioannidis data)
    n_authors: int
    # Average citations per paper (for field-normalization)
    avg_citations_per_paper: float
    # Aliases: S2 field names and Google Scholar category names that map here
    s2_aliases: list  # Semantic Scholar fieldsOfStudy names
    gs_aliases: list  # Google Scholar interest tag names


# ---- Field Benchmark Database ----
# h-index percentiles are estimated from Ioannidis citation percentiles
# using the empirical relationship h ≈ 0.54 * sqrt(total_citations)
# (Hirsch 2005, validated across fields), cross-checked with
# field-specific studies cited above.

FIELD_BENCHMARKS = {
    "Mathematics": FieldBenchmark(
        field="Mathematics & Statistics",
        citation_p25=18, citation_p50=52, citation_p75=162, citation_p90=457,
        h_p25=3, h_p50=6, h_p75=11, h_p90=18, h_p99=40,
        n_authors=96619,
        avg_citations_per_paper=2.66,
        s2_aliases=["Mathematics"],
        gs_aliases=["mathematics", "topology", "algebra", "number theory",
                     "combinatorics", "analysis", "geometry", "probability",
                     "statistics", "applied mathematics", "mathematical physics"],
    ),
    "Computer Science": FieldBenchmark(
        field="Computer Science & ICT",
        citation_p25=20, citation_p50=60, citation_p75=193, citation_p90=574,
        h_p25=3, h_p50=7, h_p75=13, h_p90=22, h_p99=55,
        n_authors=339284,
        avg_citations_per_paper=2.49,
        s2_aliases=["Computer Science"],
        gs_aliases=["computer science", "machine learning", "artificial intelligence",
                     "natural language processing", "computer vision", "algorithms",
                     "data mining", "databases", "software engineering", "robotics",
                     "distributed systems", "cryptography", "programming languages"],
    ),
    "Physics": FieldBenchmark(
        field="Physics & Astronomy",
        citation_p25=38, citation_p50=128, citation_p75=480, citation_p90=1741,
        h_p25=5, h_p50=10, h_p75=19, h_p90=35, h_p99=80,
        n_authors=667255,
        avg_citations_per_paper=5.20,
        s2_aliases=["Physics"],
        gs_aliases=["physics", "astrophysics", "condensed matter", "quantum physics",
                     "particle physics", "optics", "plasma physics", "nuclear physics",
                     "high energy physics", "theoretical physics"],
    ),
    "Chemistry": FieldBenchmark(
        field="Chemistry",
        citation_p25=45, citation_p50=129, citation_p75=362, citation_p90=989,
        h_p25=5, h_p50=10, h_p75=17, h_p90=28, h_p99=65,
        n_authors=506526,
        avg_citations_per_paper=4.50,
        s2_aliases=["Chemistry"],
        gs_aliases=["chemistry", "organic chemistry", "inorganic chemistry",
                     "physical chemistry", "analytical chemistry", "materials chemistry"],
    ),
    "Biology": FieldBenchmark(
        field="Biology",
        citation_p25=47, citation_p50=140, citation_p75=426, citation_p90=1178,
        h_p25=5, h_p50=10, h_p75=18, h_p90=30, h_p99=70,
        n_authors=236108,
        avg_citations_per_paper=8.00,
        s2_aliases=["Biology"],
        gs_aliases=["biology", "ecology", "evolutionary biology", "genetics",
                     "cell biology", "molecular biology", "microbiology",
                     "bioinformatics", "computational biology", "systems biology"],
    ),
    "Biomedical Research": FieldBenchmark(
        field="Biomedical Research",
        citation_p25=68, citation_p50=212, citation_p75=641, citation_p90=1769,
        h_p25=6, h_p50=12, h_p75=22, h_p90=37, h_p99=85,
        n_authors=626753,
        avg_citations_per_paper=10.58,
        s2_aliases=["Medicine"],
        gs_aliases=["biomedical", "biochemistry", "pharmacology", "immunology",
                     "neuroscience", "cancer research", "drug discovery"],
    ),
    "Clinical Medicine": FieldBenchmark(
        field="Clinical Medicine",
        citation_p25=41, citation_p50=141, citation_p75=467, citation_p90=1430,
        h_p25=5, h_p50=10, h_p75=19, h_p90=33, h_p99=75,
        n_authors=2113734,
        avg_citations_per_paper=10.58,
        s2_aliases=["Medicine"],
        gs_aliases=["medicine", "clinical medicine", "surgery", "cardiology",
                     "oncology", "pediatrics", "psychiatry", "radiology",
                     "epidemiology", "public health"],
    ),
    "Engineering": FieldBenchmark(
        field="Engineering",
        citation_p25=18, citation_p50=56, citation_p75=174, citation_p90=499,
        h_p25=3, h_p50=6, h_p75=12, h_p90=20, h_p99=50,
        n_authors=436723,
        avg_citations_per_paper=3.17,
        s2_aliases=["Engineering"],
        gs_aliases=["engineering", "electrical engineering", "mechanical engineering",
                     "civil engineering", "chemical engineering", "biomedical engineering",
                     "materials science", "aerospace engineering"],
    ),
    "Economics": FieldBenchmark(
        field="Economics & Business",
        citation_p25=28, citation_p50=83, citation_p75=258, citation_p90=708,
        h_p25=4, h_p50=8, h_p75=14, h_p90=24, h_p99=55,
        n_authors=108277,
        avg_citations_per_paper=4.17,
        s2_aliases=["Economics"],
        gs_aliases=["economics", "finance", "accounting", "management",
                     "marketing", "operations research", "business"],
    ),
    "Social Sciences": FieldBenchmark(
        field="Social Sciences",
        citation_p25=20, citation_p50=56, citation_p75=158, citation_p90=423,
        h_p25=3, h_p50=6, h_p75=11, h_p90=18, h_p99=45,
        n_authors=119260,
        avg_citations_per_paper=3.46,
        s2_aliases=["Sociology", "Political Science"],
        gs_aliases=["sociology", "political science", "anthropology", "education",
                     "communication", "linguistics", "geography", "social sciences"],
    ),
    "Psychology": FieldBenchmark(
        field="Psychology & Cognitive Sciences",
        citation_p25=41, citation_p50=128, citation_p75=403, citation_p90=1198,
        h_p25=5, h_p50=10, h_p75=18, h_p90=30, h_p99=70,
        n_authors=96159,
        avg_citations_per_paper=8.24,
        s2_aliases=["Psychology"],
        gs_aliases=["psychology", "cognitive science", "behavioral science",
                     "neuropsychology"],
    ),
    "Earth Sciences": FieldBenchmark(
        field="Earth & Environmental Sciences",
        citation_p25=40, citation_p50=126, citation_p75=405, citation_p90=1192,
        h_p25=5, h_p50=10, h_p75=18, h_p90=30, h_p99=65,
        n_authors=223246,
        avg_citations_per_paper=6.00,
        s2_aliases=["Geology", "Geography", "Environmental Science"],
        gs_aliases=["earth science", "geology", "geophysics", "climate science",
                     "oceanography", "atmospheric science", "environmental science"],
    ),
    "Philosophy": FieldBenchmark(
        field="Philosophy & Theology",
        citation_p25=12, citation_p50=32, citation_p75=87, citation_p90=217,
        h_p25=2, h_p50=4, h_p75=8, h_p90=13, h_p99=30,
        n_authors=13861,
        avg_citations_per_paper=2.00,
        s2_aliases=["Philosophy"],
        gs_aliases=["philosophy", "theology", "ethics", "logic"],
    ),
    "History": FieldBenchmark(
        field="Historical Studies",
        citation_p25=16, citation_p50=40, citation_p75=105, citation_p90=263,
        h_p25=3, h_p50=5, h_p75=9, h_p90=14, h_p99=30,
        n_authors=25277,
        avg_citations_per_paper=2.00,
        s2_aliases=["History"],
        gs_aliases=["history", "art history", "archaeology"],
    ),
    "Materials Science": FieldBenchmark(
        field="Materials Science",
        citation_p25=30, citation_p50=90, citation_p75=280, citation_p90=800,
        h_p25=4, h_p50=8, h_p75=15, h_p90=25, h_p99=60,
        n_authors=300000,
        avg_citations_per_paper=4.50,
        s2_aliases=["Materials Science"],
        gs_aliases=["materials science", "nanotechnology", "polymers",
                     "ceramics", "metallurgy"],
    ),
    "Linguistics": FieldBenchmark(
        field="Linguistics",
        citation_p25=15, citation_p50=45, citation_p75=130, citation_p90=350,
        h_p25=3, h_p50=5, h_p75=10, h_p90=17, h_p99=40,
        n_authors=30000,
        avg_citations_per_paper=3.00,
        s2_aliases=["Linguistics"],
        gs_aliases=["linguistics", "computational linguistics", "phonetics",
                     "syntax", "semantics", "pragmatics", "sociolinguistics"],
    ),
}

# Default fallback for unknown fields
DEFAULT_BENCHMARK = FieldBenchmark(
    field="All Fields (General)",
    citation_p25=29, citation_p50=102, citation_p75=346, citation_p90=1077,
    h_p25=4, h_p50=8, h_p75=16, h_p90=28, h_p99=60,
    n_authors=6880389,
    avg_citations_per_paper=5.00,
    s2_aliases=[],
    gs_aliases=[],
)


def match_field(field_name: str) -> Optional[FieldBenchmark]:
    """Match a field name (from S2 or GS) to the closest benchmark."""
    if not field_name:
        return None
    name_lower = field_name.lower().strip()

    # Direct key match
    for key, bench in FIELD_BENCHMARKS.items():
        if key.lower() == name_lower:
            return bench

    # S2 alias match
    for bench in FIELD_BENCHMARKS.values():
        for alias in bench.s2_aliases:
            if alias.lower() == name_lower:
                return bench

    # GS alias match (substring)
    for bench in FIELD_BENCHMARKS.values():
        for alias in bench.gs_aliases:
            if alias in name_lower or name_lower in alias:
                return bench

    return None


def infer_percentile(value: float, p25: float, p50: float, p75: float, p90: float, p99: float = None) -> float:
    """
    Estimate a percentile rank given benchmark percentile values.
    Uses piecewise linear interpolation between known percentile points.
    Returns a value in [0, 100].
    """
    if p99 is None:
        p99 = p90 * 2.5  # rough estimate

    breakpoints = [
        (0, 0),
        (p25, 25),
        (p50, 50),
        (p75, 75),
        (p90, 90),
        (p99, 99),
    ]

    if value <= 0:
        return 0.0

    for i in range(1, len(breakpoints)):
        v_lo, pct_lo = breakpoints[i - 1]
        v_hi, pct_hi = breakpoints[i]
        if value <= v_hi:
            if v_hi == v_lo:
                return pct_lo
            frac = (value - v_lo) / (v_hi - v_lo)
            return pct_lo + frac * (pct_hi - pct_lo)

    # Above p99 — extrapolate gently
    if value > p99:
        extra = min((value - p99) / p99 * 0.5, 0.99)
        return 99.0 + extra
    return 99.5


def get_h_percentile(h_index: int, benchmark: FieldBenchmark) -> float:
    """Get the estimated percentile rank for an h-index within a field."""
    return infer_percentile(
        h_index,
        benchmark.h_p25, benchmark.h_p50, benchmark.h_p75, benchmark.h_p90, benchmark.h_p99
    )


def get_citation_percentile(total_citations: int, benchmark: FieldBenchmark) -> float:
    """Get the estimated percentile rank for total citations within a field."""
    return infer_percentile(
        total_citations,
        benchmark.citation_p25, benchmark.citation_p50, benchmark.citation_p75, benchmark.citation_p90,
        benchmark.citation_p90 * 3  # rough p99 estimate
    )


def percentile_to_label(pct: float) -> str:
    """Convert a percentile to a human-readable label."""
    if pct >= 99:
        return "Top 1% (Elite)"
    elif pct >= 95:
        return "Top 5% (Exceptional)"
    elif pct >= 90:
        return "Top 10% (Outstanding)"
    elif pct >= 75:
        return "Top 25% (Very Good)"
    elif pct >= 50:
        return "Top 50% (Above Median)"
    elif pct >= 25:
        return "Below Median"
    else:
        return "Bottom Quartile"
