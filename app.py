"""
Gradio web interface for the Citation Analyzer.

Two tabs:
  1. Full Profile (OpenAlex) — sub-field benchmarks, distribution shape, breadth
  2. Multi-Source (S2 + GS) — cross-platform comparison with static field benchmarks

Run:
    python app.py
"""

import json
import gradio as gr

from openalex_fetcher import (
    search_openalex_author, full_analysis, format_full_report,
)
from fetchers import search_semantic_scholar, search_google_scholar, S2_API_KEY_ENV
from ranker import rank_author, format_report
from benchmarks import FIELD_BENCHMARKS


# ── OpenAlex tab: search → select → analyze ──

def oa_search(name):
    """Search OpenAlex and populate the candidate list."""
    if not name or not name.strip():
        return [], gr.Dropdown(choices=["(search for an author first)"], value=None), ""

    all_candidates = search_openalex_author(name.strip())

    # Filter to candidates whose name contains all search terms
    search_terms = name.strip().lower().split()
    candidates = [
        c for c in all_candidates
        if all(term in c.name.lower() for term in search_terms)
    ]

    if not candidates:
        return [], gr.Dropdown(choices=["(no results found)"], value=None), "No results found."

    labels = []
    for i, c in enumerate(candidates):
        topics = ", ".join(t["display_name"] for t in c.topics[:3]) if c.topics else "—"
        aff = c.affiliations[0] if c.affiliations else ""
        label = f"{c.name} — h={c.h_index}, cit={c.cited_by_count:,}"
        if aff:
            label += f" ({aff})"
        label += f"  [{topics}]"
        labels.append(label)

    # Store serialized candidates in state as list of dicts
    state = [{"idx": i, "id": c.openalex_id} for i, c in enumerate(candidates)]

    return (
        candidates,
        gr.Dropdown(choices=labels, value=labels[0]),
        f"Found {len(candidates)} candidates. Select one and click **Analyze**.",
    )


def oa_analyze(candidates, selected_label, topic, n_benchmarks):
    """Run full analysis on the selected candidate."""
    if not candidates or not selected_label:
        return "Search for an author first.", "{}"

    # Find which candidate was selected by matching the label
    idx = 0
    for i, c in enumerate(candidates):
        topics = ", ".join(t["display_name"] for t in c.topics[:3]) if c.topics else "—"
        aff = c.affiliations[0] if c.affiliations else ""
        label = f"{c.name} — h={c.h_index}, cit={c.cited_by_count:,}"
        if aff:
            label += f" ({aff})"
        label += f"  [{topics}]"
        if label == selected_label:
            idx = i
            break

    author = candidates[idx]
    topic = topic.strip() if topic else None
    n_benchmarks = int(n_benchmarks)

    analysis = full_analysis(
        author.name, preferred_topic=topic,
        benchmark_top_n=n_benchmarks, author=author,
    )

    if "error" in analysis:
        return f"**Error:** {analysis['error']}", "{}"

    report = format_full_report(analysis)

    author_obj = analysis["author"]
    json_data = {
        "name": author_obj.name,
        "h_index": author_obj.h_index,
        "i10_index": author_obj.i10_index,
        "cited_by_count": author_obj.cited_by_count,
        "works_count": author_obj.works_count,
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

    return f"```\n{report}\n```", json.dumps(json_data, indent=2)


# ── Multi-source tab: search → select → analyze ──

def _ms_label(c):
    """Build a display label for an AuthorMetrics candidate."""
    label = f"{c.name} — h={c.h_index}, cit={c.total_citations or 0:,}"
    if c.affiliations:
        label += f" ({c.affiliations[0]})"
    if c.fields:
        label += f"  [{', '.join(c.fields[:3])}]"
    return label


def ms_search(name, source):
    """Search S2 and/or GS and populate candidate dropdowns."""
    if not name or not name.strip():
        return ([], [], gr.Dropdown(choices=["(search first)"], value=None),
                gr.Dropdown(choices=["(search first)"], value=None), "")

    search_terms = name.strip().lower().split()

    s2_all = []
    gs_all = []
    errors = []

    if source in ("Both", "Semantic Scholar only"):
        try:
            s2_all = search_semantic_scholar(name.strip())
        except Exception as e:
            errors.append(f"S2: {e}")

    if source in ("Both", "Google Scholar only"):
        try:
            gs_all = search_google_scholar(name.strip())
        except Exception as e:
            errors.append(f"GS: {e}")

    # Filter by name match
    s2_filtered = [c for c in s2_all if all(t in c.name.lower() for t in search_terms)]
    gs_filtered = [c for c in gs_all if all(t in c.name.lower() for t in search_terms)]

    s2_labels = [_ms_label(c) for c in s2_filtered] if s2_filtered else ["(no S2 results)"]
    gs_labels = [_ms_label(c) for c in gs_filtered] if gs_filtered else ["(no GS results)"]

    parts = []
    if s2_filtered:
        parts.append(f"{len(s2_filtered)} S2")
    if gs_filtered:
        parts.append(f"{len(gs_filtered)} GS")
    if errors:
        parts.append("; ".join(errors))

    status = f"Found {', '.join(parts)} candidates." if parts else "No results found."

    return (
        s2_filtered,
        gs_filtered,
        gr.Dropdown(choices=s2_labels, value=s2_labels[0] if s2_filtered else None),
        gr.Dropdown(choices=gs_labels, value=gs_labels[0] if gs_filtered else None),
        status,
    )


def ms_analyze(s2_candidates, gs_candidates, s2_label, gs_label, field):
    """Run ranking on the selected S2 and GS candidates."""
    if not s2_candidates and not gs_candidates:
        return "Search for an author first."

    field = field if field and field != "Auto-detect" else None

    # Find selected S2 candidate
    s2_pick = []
    if s2_candidates and s2_label:
        for c in s2_candidates:
            if _ms_label(c) == s2_label:
                s2_pick = [c]
                break

    # Find selected GS candidate
    gs_pick = []
    if gs_candidates and gs_label:
        for c in gs_candidates:
            if _ms_label(c) == gs_label:
                gs_pick = [c]
                break

    if not s2_pick and not gs_pick:
        return "Select at least one candidate."

    result = rank_author(s2_pick, gs_pick, preferred_field=field)
    report = format_report(result)
    return f"```\n{report}\n```"


# ── Build UI ──

field_choices = ["Auto-detect"] + sorted(FIELD_BENCHMARKS.keys())
s2_status = "loaded from .env" if S2_API_KEY_ENV else "not set (unauthenticated, slower rate limits)"

with gr.Blocks(title="Citation Analyzer") as app:
    gr.Markdown("# Citation Analyzer\nContextualize researcher metrics against field-specific benchmarks.")

    with gr.Tabs():
        # ── Tab 1: OpenAlex Full Profile ──
        with gr.Tab("Full Profile (OpenAlex)"):
            gr.Markdown("Live empirical sub-field benchmarks from OpenAlex's full author database.")

            # State to hold candidate objects between search and analyze
            oa_state = gr.State([])

            with gr.Row():
                with gr.Column(scale=1):
                    oa_name = gr.Textbox(label="Researcher name", placeholder="e.g. Igor Rivin")
                    oa_search_btn = gr.Button("Search", variant="secondary")
                    oa_status = gr.Markdown("")
                    oa_dropdown = gr.Dropdown(
                        label="Select author",
                        choices=["(search for an author first)"],
                        value=None,
                        interactive=True,
                    )
                    oa_topic = gr.Textbox(label="Topic override (optional)",
                                          placeholder="e.g. Algebraic Topology")
                    oa_n = gr.Slider(minimum=1, maximum=10, value=3, step=1,
                                     label="Number of topics to benchmark")
                    oa_btn = gr.Button("Analyze", variant="primary")
                with gr.Column(scale=2):
                    oa_report = gr.Markdown(label="Report")
                    with gr.Accordion("Raw JSON data", open=False):
                        oa_json = gr.Code(language="json", label="JSON")

            oa_search_btn.click(
                fn=oa_search,
                inputs=[oa_name],
                outputs=[oa_state, oa_dropdown, oa_status],
            )
            oa_btn.click(
                fn=oa_analyze,
                inputs=[oa_state, oa_dropdown, oa_topic, oa_n],
                outputs=[oa_report, oa_json],
            )

        # ── Tab 2: Multi-Source (S2 + GS) ──
        with gr.Tab("Multi-Source (S2 + GS)"):
            gr.Markdown(
                f"Cross-platform comparison using static field benchmarks (Ioannidis 2019).\n\n"
                f"S2 API key: **{s2_status}**"
            )

            ms_s2_state = gr.State([])
            ms_gs_state = gr.State([])

            with gr.Row():
                with gr.Column(scale=1):
                    ms_name = gr.Textbox(label="Researcher name", placeholder="e.g. Timothy Gowers")
                    ms_source = gr.Radio(
                        choices=["Both", "Semantic Scholar only", "Google Scholar only"],
                        value="Both", label="Sources")
                    ms_search_btn = gr.Button("Search", variant="secondary")
                    ms_status = gr.Markdown("")
                    ms_s2_dd = gr.Dropdown(
                        label="Semantic Scholar candidate",
                        choices=["(search first)"], value=None, interactive=True,
                    )
                    ms_gs_dd = gr.Dropdown(
                        label="Google Scholar candidate",
                        choices=["(search first)"], value=None, interactive=True,
                    )
                    ms_field = gr.Dropdown(choices=field_choices, value="Auto-detect",
                                           label="Field override")
                    ms_btn = gr.Button("Analyze", variant="primary")
                with gr.Column(scale=2):
                    ms_report = gr.Markdown(label="Report")

            ms_search_btn.click(
                fn=ms_search,
                inputs=[ms_name, ms_source],
                outputs=[ms_s2_state, ms_gs_state, ms_s2_dd, ms_gs_dd, ms_status],
            )
            ms_btn.click(
                fn=ms_analyze,
                inputs=[ms_s2_state, ms_gs_state, ms_s2_dd, ms_gs_dd, ms_field],
                outputs=[ms_report],
            )

    gr.Markdown(
        "---\n"
        "*Data: [OpenAlex](https://openalex.org), Semantic Scholar, Google Scholar. "
        "Benchmarks: Ioannidis et al. (2019). "
        "Percentiles are approximate — see caveats in each report.*"
    )


if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7864)
