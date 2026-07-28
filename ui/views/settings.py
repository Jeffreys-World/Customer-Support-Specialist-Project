"""Settings — what's loaded, and full disclosure on simulated data.

The disclosure section is not decoration. D1 traded a visible "simulated" badge
for a layout that matches the reference, and this page is where that promise is
paid in full: every simulated field, named, in one place.
"""

from __future__ import annotations

import streamlit as st

from ui import components as c
from ui import domain


def render() -> None:
    c.app_bar("Settings", "Data source, and what's real versus simulated.")

    source = domain.active_data_source()
    left, right = st.columns([1, 1], gap="medium")

    with left:
        with st.container(border=True):
            c.panel_title("Data source")
            c.field("Loaded file", source.name if source else "none found")
            c.field("Tickets", len(domain.load_tickets()))
            c.field("Override log", "present" if domain.OVERRIDE_LOG.exists() else "not created yet")
            if source and source.name.endswith("sample.json"):
                st.caption(
                    "Running on the committed demo sample. Run "
                    "`python -m src.batch_classify` for the full batch."
                )

        with st.container(border=True):
            c.panel_title("SLA targets")
            for cat, hours in domain.SLA_HOURS.items():
                c.field(cat.value, f"{hours}h")
            st.caption(
                "Ticket age is derived from a hash of the ticket id — the dataset "
                "has no timestamps, so the countdown is a stable demo clock."
            )

    with right:
        with st.container(border=True):
            c.panel_title("Real data")
            st.markdown(
                "- Priority, urgency score, and category\n"
                "- Matched keyword signals\n"
                "- Critical-class safety-net state\n"
                "- The AI rationale and suggested queue\n"
                "- Ticket subject, body, and tags\n"
                "- Dataset ground-truth labels\n"
                "- Your confirm/override decisions "
                "(`results/override_log.csv`)\n"
                "- Agreement statistics computed from that log"
            )

        with st.container(border=True):
            c.panel_title("Simulated for demonstration", badge=True)
            st.markdown(
                "- Requester name, email, phone, organization, and local time\n"
                "- Agent reply turns in the conversation thread\n"
                "- Interaction history\n"
                "- Ticket age and the SLA countdown"
            )
            st.caption(
                "The dataset behind this project has no requester identity, "
                "timestamps, or message threads. These fields are derived "
                "deterministically from the ticket id so they stay stable across "
                "reruns, and none of them influences triage."
            )
