"""Completed work → Last 30 days.

Backed by ``results/override_log.csv`` — every confirm/adjust the agent has made.
That log is real: it's the same file the project's manual spot-check evaluation
reads from.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import components as c
from ui import domain


def render() -> None:
    rows = domain.reviewed_recently(days=30)
    stats = domain.agreement_stats()

    c.app_bar(
        "Completed work",
        "Priorities you've confirmed or adjusted in the last 30 days.",
        chip=f"{c.count(len(rows))} reviewed",
    )

    if not rows:
        c.empty_state(
            "Nothing reviewed yet. Open a ticket and confirm or adjust its priority "
            "— every decision lands here and in results/override_log.csv."
        )
        return

    left, right = st.columns([7, 3], gap="medium")

    with left:
        c.section("Review log")
        df = pd.DataFrame(rows)
        df = df.rename(columns={
            "timestamp": "When",
            "ticket_id": "Ticket",
            "ai_category": "AI said",
            "agent_category": "You said",
            "action": "Action",
        })
        # Height tracks the rows there actually are, capped so a long log scrolls
        # instead of pushing the page. A flat height=460 meant the first review a
        # reviewer logs sat above roughly a dozen blank striped rows — the panel
        # read as a table that had failed to load rather than one with a single
        # entry, on the page whose entire job is showing that the log works.
        # 35px/row + 38px header matches Streamlit's own grid metrics.
        st.dataframe(
            df, use_container_width=True, hide_index=True,
            height=min(460, 38 + 35 * len(df)),
        )

    with right:
        with st.container(border=True):
            c.stat_block(
                "Agreement statistics", f"{c.count(stats['total'])} reviewed all time",
                [
                    ("Agreed", f"{stats['agreement_pct']}%", "var(--tc-low)"),
                    ("Overridden", stats["overridden"], "var(--tc-muted)"),
                ],
            )
            st.caption(
                "A low agreement rate is a signal to retune the scorer's keyword "
                "weights, not a UI problem."
            )
