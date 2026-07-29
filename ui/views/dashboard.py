"""Dashboard — ticket analytics, and the measured model results beneath them.

Renamed from "Reporting". The old page was only an embedded copy of
``results/evaluation.md``; this one leads with the queue analytics an agent
actually opens a dashboard to see, and keeps the evaluation report below them.

The evaluation numbers are still rendered from ``results/evaluation.md``
(produced by ``python -m src.evaluate``) rather than restated, so the console can
never drift from the committed report.
"""

from __future__ import annotations

import re

import streamlit as st

from ui import components as c
from ui import domain

EVALUATION_REPORT = domain.REPO_ROOT / "results" / "evaluation.md"

# Markdown ATX headings, but not inside a fenced code block.
_HEADING = re.compile(r"^(#{1,5})(\s+\S)", re.MULTILINE)
_FENCE = re.compile(r"^```", re.MULTILINE)


def demote_headings(markdown: str, levels: int = 2) -> str:
    """Push an embedded document's headings below the page's own.

    ``results/evaluation.md`` is a standalone report, so it opens with an h1.
    Rendered as-is inside the Reporting page, that h1 came out larger than the
    page title above it and read as the start of a new document rather than a
    panel within this one. Demoting by two levels puts the report's h1 under the
    page's h1 and its section headings under the page's h2. Found by /qa.

    Fenced code blocks are skipped so a ``#`` comment in a shell example is not
    mistaken for a heading.
    """
    out, in_fence = [], False
    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            line = _HEADING.sub(lambda m: "#" * min(len(m.group(1)) + levels, 6) + m.group(2), line)
        out.append(line)
    return "\n".join(out)


def render() -> None:
    tickets = domain.load_tickets()
    counts = domain.category_counts(tickets)

    c.app_bar(
        "Dashboard",
        "Queue composition, and how the scorer performs against the dataset's labels.",
        chip=f"{len(tickets)} tickets classified",
    )

    c.section("Queue composition")
    c.priority_bar(counts)
    st.caption(
        "Live distribution of the loaded batch. Source: "
        f"`{domain.active_data_source().name if domain.active_data_source() else 'none'}`."
    )

    st.html("<div style='height:.8rem'></div>")
    c.section("Evaluation report")

    if EVALUATION_REPORT.exists():
        with st.container(border=True):
            st.markdown(demote_headings(EVALUATION_REPORT.read_text(encoding="utf-8")))
        st.caption(f"Rendered from `results/{EVALUATION_REPORT.name}`. Regenerate with `python -m src.evaluate`.")
    else:
        c.empty_state(
            "No evaluation report found. Run `python -m src.evaluate` to generate "
            "results/evaluation.md."
        )
