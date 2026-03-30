# Citation Analyzer — Academic "Pecking Order" Tool

Given a researcher's name, this tool pulls citation metrics from multiple
sources, infers sub-field(s), and contextualizes everything against
empirical benchmarks — accounting for field differences, research breadth,
and citation distribution shape.

## Quick Start

```bash
pip install scholarly   # only needed for Google Scholar; OpenAlex needs nothing

# Full profile with sub-field benchmarks, distribution shape, breadth metrics
python openalex_fetcher.py "Igor Rivin"
python openalex_fetcher.py "Yoshua Bengio"
python openalex_fetcher.py "Terence Tao" --topic "Algebraic Topology"

# JSON output for programmatic use
python openalex_fetcher.py "Geoffrey Hinton" --json

# Benchmark against more topics (default: 3)
python openalex_fetcher.py "Igor Rivin" --benchmarks 5

# Classic multi-source analysis (Google Scholar + Semantic Scholar)
python analyzer.py "Timothy Gowers" --field Mathematics --s2-only
python analyzer.py "Andrew Ng" --json
python analyzer.py --list-fields x
```

## What It Reports

### 1. Standard metrics
h-index, i10-index, total citations, papers, citations/paper — from OpenAlex
(or optionally Google Scholar + Semantic Scholar via `analyzer.py`).

### 2. L∞ and citation distribution shape
- **c_max** (most-cited paper) and c_2, c_5, c_10
- **c_max / c_2 ratio** — "spikiness": how much the top paper dominates.
  Low (~1) = steady output; high (>5) = one breakthrough paper.
- **c_max / h²** — peak impact relative to breadth. A value of ~0.5 means
  the top paper is roughly what the h-index predicts; >>1 means a spike.
- **Gini coefficient** — overall citation inequality (0 = equal, 1 = all in one paper)
- **Top-k concentration** — fraction of total citations from top 1/5/10 papers

Example contrast:
```
                        Rivin       Bengio      Vaswani
c_max / c_2             1.1x        1.4x        21.2x
Top-1 paper share       9.8%        17.7%       65.3%
Unique topics           69          195         21
```

### 3. Research breadth (for generalists)
- **Unique topics / subfields** — how many OpenAlex topics your papers span
- **Effective topics (1/HHI)** — information-theoretic measure of diversity;
  a researcher spread across 69 topics with entropy 0.87 has ~21 "effective" topics
- **Normalized Shannon entropy** — 0 = all papers in one topic, 1 = uniform
- **Per-subfield paper counts**

### 4. Per-topic h-index decomposition
Instead of one global h-index benchmarked against one field, this decomposes
the h-index by OpenAlex topic. For a generalist, this is far more informative:

```
Topic                                    Papers   h   Cites  c_max
Geometric and Algebraic Topology             29   9     701    242
Mathematical Dynamics and Fractals            9   6     152     52
Computational Geometry and Mesh Gen.         11   5     530    213
Limits and Structures in Graph Theory         9   4      78     29
...
```

### 5. Sub-field percentile benchmarks
For each of the author's top topics, the tool queries OpenAlex's `group_by`
API to compute the **exact empirical h-index CDF** for all authors tagged
with that topic. This gives real percentile ranks, not approximations.

The sub-field granularity matters enormously:

```
Topic                           Authors   p90 h   p99 h
Algebraic Geometry & NT          42,751       8      26
Geometric & Algebraic Topology   33,649       8      25
Nonlinear PDEs                   28,452      10      31
Navier-Stokes Equations          12,759      10      33
```

### 6. Career-stage context
- **First publication year** and years active
- **m-quotient** (h / years) — Hirsch's career-length normalization
- **Papers/year** and **citations/year**
- **Recent momentum** — fraction of citations from the last 3 years

## Architecture

```
openalex_fetcher.py   ← Primary tool. OpenAlex API, sub-field benchmarks,
│                       per-topic decomposition, distribution shape, breadth.
│                       No dependencies beyond Python stdlib.
│
analyzer.py           ← Multi-source tool. Queries Google Scholar (via scholarly)
│                       and Semantic Scholar. Uses static field benchmarks.
├── fetchers.py       ← GS + S2 data fetching
├── benchmarks.py     ← Static percentile tables (Ioannidis 2019, 22 fields)
└── ranker.py         ← Ranking engine and report formatter
```

### Data sources

| Source | Access | Dependencies | Strengths |
|--------|--------|--------------|-----------|
| **OpenAlex** | Free REST API, no key needed | None (stdlib only) | Best for sub-field benchmarks. 4,500 topics, 200M+ works. Live empirical CDFs via group_by. |
| **Semantic Scholar** | Free REST API (key for higher limits) | None | Good field-of-study data per paper. Fragmented author profiles are a known issue. |
| **Google Scholar** | `scholarly` library (unofficial) | `pip install scholarly` | Most complete coverage (books, theses, patents). i10-index. Aggressively rate-limited. |

### Benchmark data for `analyzer.py`

The static benchmarks in `benchmarks.py` are derived from:
- **Ioannidis et al. (2019)** — career-long percentiles for 22 fields,
  6.88M scientists. [PLoS Biology](https://pmc.ncbi.nlm.nih.gov/articles/PMC6699798/)
- **Iglesias & Pecharromán (2007)** — h-index distributions for HCRs.
  [arXiv:1708.07893](https://arxiv.org/pdf/1708.07893)

## Known Limitations

1. **Career-stage monotonicity.** The h-index can only increase, so
   a beginner always trails a senior researcher. The m-quotient (h/years)
   partially corrects for this but assumes linear growth (empirically
   concave). A proper correction needs E[h | field, career_length],
   which is estimable from OpenAlex data but not yet computed here.

2. **Generalist penalty.** The h-index penalizes breadth: citations are
   scattered across communities that don't cite each other. The per-topic
   decomposition addresses this by showing consistent excellence across
   many fields, but no single scalar captures "generalist impact."

3. **Sub-field granularity.** OpenAlex's ~4,500 topics are much better than
   "Mathematics" vs "Physics," but still imperfect. PDE people cite more
   than algebraic geometers even within "Mathematics." The live benchmarks
   handle this well for well-populated topics.

4. **L∞ limitations.** The most-cited paper may be a review, survey, or
   multi-author collaborative work (e.g., Bengio's "Deep Learning" with
   LeCun and Hinton is a Nature review, not a single-author breakthrough).
   The c_max metric doesn't distinguish paper types.

5. **Author disambiguation.** All three platforms (OpenAlex, S2, GS) have
   disambiguation issues. Common names may match the wrong person. OpenAlex
   sometimes merges or fragments author profiles. Always verify the profile URL.

## Programmatic Usage

```python
from openalex_fetcher import full_analysis, format_full_report

# Full analysis
analysis = full_analysis("Igor Rivin", preferred_topic="Algebraic Topology")
print(format_full_report(analysis))

# Access structured data
author = analysis["author"]
print(f"h-index: {author.h_index}")
print(f"Breadth: {analysis['breadth']['effective_topics']:.0f} effective topics")
print(f"Spikiness: {analysis['shape']['c_max_over_c2']:.1f}x")

# Per-topic breakdown
for topic, data in analysis["per_topic"][:10]:
    print(f"  {topic}: h={data['h']}, {data['n_papers']} papers, {data['total_cites']} cites")

# Sub-field percentile
for topic, rank in analysis["rankings"].items():
    print(f"  {topic}: {rank['h_percentile']:.1f}th percentile ({rank['total_authors']:,} authors)")
```
