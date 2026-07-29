"""Home — the morning view.

Deliberately not a second copy of the queue. Home answers "what does my day look
like and what needs me right now"; Tickets is the full filterable list. The
reference's home screen is the same split: a compact work list on the left,
statistics on the right.
"""

from __future__ import annotations

import streamlit as st

from ui import components as c
from ui import domain, state


def render() -> None:
    tickets = domain.load_tickets()
    counts = domain.category_counts(tickets)

    c.app_bar(
        "Home",
        "Your queue arrived pre-sorted. Start at the top.",
        chip=f"{len(tickets)} tickets in queue",
    )

    toast = state.pop_last_action()
    if toast:
        st.success(toast)

    c.priority_bar(counts)
    st.html("<div style='height:.6rem'></div>")

    left, right = st.columns([7, 3], gap="medium")

    with left:
        c.section("Needs attention now")
        st.caption(
            "Highest urgency first, and anything the safety net escalated. "
            "Open one to see why it scored the way it did."
        )

        urgent = sorted(
            [t for t in tickets if t["category"] in ("Critical", "High")
             or t.get("safety_net_triggered")],
            key=domain.sort_key,
        )[:state.attention_limit()]

        if not urgent:
            c.empty_state("Nothing urgent in the queue. That's a good morning.")
        for ticket in urgent:
            if c.ticket_row(ticket, key=f"home_open_{ticket['id']}"):
                state.open_ticket(ticket["id"])
                st.switch_page(st.session_state["_page_tickets"])

        breached = sum(1 for t in tickets if domain.sla_breached(t))
        if breached:
            st.caption(f"{breached} ticket(s) in the full queue are past their SLA target.")

    with right:
        _statistics(tickets, counts)


def _statistics(tickets, counts) -> None:
    net = sum(1 for t in tickets if t.get("safety_net_triggered"))
    breached = sum(1 for t in tickets if domain.sla_breached(t))

    with st.container(border=True):
        c.stat_block(
            "Triage statistics", "This queue",
            [
                ("Critical", counts["Critical"], "var(--tc-critical)"),
                ("High", counts["High"], "var(--tc-high)"),
                ("Past SLA", breached, "var(--tc-muted)"),
            ],
        )
        st.caption(f"{net} escalated by the Critical-class safety net.")

    with st.container(border=True):
        stats = domain.agreement_stats()
        if stats["total"]:
            c.stat_block(
                "Agreement statistics", f"{stats['total']} reviewed",
                [
                    ("Agreed with AI", f"{stats['agreement_pct']}%", "var(--tc-low)"),
                    ("Overridden", stats["overridden"], "var(--tc-muted)"),
                ],
            )
            st.caption("How often you kept the AI's priority. The agent always has final say.")
        else:
            c.stat_block("Agreement statistics", "No reviews yet",
                         [("Reviewed", 0, "var(--tc-muted)")])
            st.caption("Confirm or override a ticket to start building this.")

    with st.container(border=True):
        c.panel_title("Following")
        followed = state.following()
        if followed:
            st.write(f"**{len(followed)}** ticket(s) starred.")
        else:
            st.caption("Star a ticket from its detail view to watch it here.")
