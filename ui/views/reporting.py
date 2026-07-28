"""Reporting — the measured results, surfaced in the product.

The evaluation numbers already exist in ``results/evaluation.md`` (produced by
``python -m src.evaluate``). Rendering them here rather than restating them means
the console can never drift from the committed report.
"""

from __future__ import annotations

import streamlit as st

from ui import components as c
from ui import domain

EVALUATION_REPORT = domain.REPO_ROOT / "results" / "evaluation.md"


def render() -> None:
    tickets = domain.load_tickets()
    counts = domain.category_counts(tickets)

    c.app_bar(
        "Reporting",
        "How the scorer performs against the dataset's own labels.",
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
            st.markdown(EVALUATION_REPORT.read_text(encoding="utf-8"))
        st.caption(f"Rendered from `results/{EVALUATION_REPORT.name}`. Regenerate with `python -m src.evaluate`.")
    else:
        c.empty_state(
            "No evaluation report found. Run `python -m src.evaluate` to generate "
            "results/evaluation.md."
        )
