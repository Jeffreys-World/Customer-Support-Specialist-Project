"""The queue: a filtered ticket list, and the detail view when one is open.

A ticket opens *inside* this view rather than as its own navigation entry, which
is how Zendesk works — opening a ticket adds a tab to the workspace, it doesn't
take you somewhere else. ``ui.state`` holds the open-tab list.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import streamlit as st

from ui import components as c
from ui import domain, state
from ui.views import ticket_detail

PAGE_SIZE = 25


def _apply_sort(tickets: List[Dict], sort: str) -> List[Dict]:
    if sort == "Oldest first":  # longest-waiting first — the SLA-risk lens
        return sorted(tickets, key=lambda t: -domain.simulated_age_hours(t["id"]))
    if sort == "Highest score":
        return sorted(tickets, key=lambda t: -int(t.get("score", 0)))
    return sorted(tickets, key=domain.sort_key)


def render_queue(
    tickets: List[Dict],
    title: str,
    subtitle: str,
    key_prefix: str,
    empty_message: str = "No tickets match these filters.",
    show_queue_filter: bool = True,
) -> None:
    """Filter row, statistics rail, and the paged list of ticket rows."""
    # The header renders above the filter row but must report the *filtered*
    # count, so it is reserved now and written after filtering. Reporting
    # len(tickets) here is ISSUE-001 exactly: a header that reads 11923 while the
    # list below it shows six. See tests/test_app_smoke.py.
    header = st.empty()

    toast = state.pop_last_action()
    if toast:
        st.success(toast)

    filters = c.filter_row(key_prefix, show_queue=show_queue_filter)
    filtered = domain.filter_tickets(
        tickets,
        categories=filters["categories"] or None,
        queues=filters["queues"] or None,
        query=str(filters["query"]),
    )
    filtered = _apply_sort(filtered, str(filters["sort"]))

    with header:
        c.app_bar(title, subtitle, chip=f"{len(filtered):,} in view")

    st.html("<div style='height:.35rem'></div>")
    left, right = st.columns([7, 3], gap="medium")

    with left:
        # Separators and singular/plural: the queue routinely holds four-figure
        # counts, and a filter matching exactly one read "1 tickets".
        c.section(f"{len(filtered):,} ticket{'' if len(filtered) == 1 else 's'}")
        if not filtered:
            # Empty queue is a state, not an exit. Returning here used to skip the
            # `with right:` block below, so an over-narrow filter collapsed the
            # two-column layout and took the statistics rail with it — including
            # Agreement statistics, which describes the review log and has nothing
            # to do with how many tickets happen to match. Found by /qa.
            c.empty_state(empty_message)
        else:
            shown_key = f"{key_prefix}_shown"
            shown = st.session_state.get(shown_key, PAGE_SIZE)
            for ticket in filtered[:shown]:
                if c.ticket_row(ticket, key=f"{key_prefix}_open_{ticket['id']}"):
                    state.open_ticket(ticket["id"])
                    st.rerun()

            if shown < len(filtered):
                st.caption(f"Showing {shown:,} of {len(filtered):,}.")
                if st.button("Load more", key=f"{key_prefix}_more", use_container_width=True):
                    st.session_state[shown_key] = shown + PAGE_SIZE
                    st.rerun()

    with right:
        _statistics_rail(filtered)


def _statistics_rail(tickets: List[Dict]) -> None:
    """Right-hand cards. Both are computed from real data — nothing simulated here."""
    counts = domain.category_counts(tickets)
    breached = sum(1 for t in tickets if domain.sla_breached(t))
    net = sum(1 for t in tickets if t.get("safety_net_triggered"))

    # The safety-net count earns its place on Tickets, where it says how much of
    # the queue the scorer overrode. On Safety-net escalations every ticket in
    # view triggered it by definition, so the figure just restated the header:
    # "1,525 tickets" on the left, "Safety net 1,525" on the right. Two identical
    # numbers on one screen reads as a coincidence worth checking rather than a
    # tautology, which costs the reader attention for nothing.
    #
    # Derived here rather than passed in as a flag. `render_queue` already takes
    # five parameters and a sixth boolean is the shape this file is trying not to
    # grow; the rail can see the answer in the data it was handed.
    # Found by /qa (ISSUE-006).
    stats: List[Tuple[str, object, str]] = [
        ("Critical", counts["Critical"], "var(--tc-critical)"),
        ("High", counts["High"], "var(--tc-high)"),
    ]
    if tickets and net < len(tickets):
        stats.append(("Safety net", net, "var(--tc-primary)"))

    with st.container(border=True):
        c.stat_block("Triage statistics", "Tickets in view", stats)
        st.caption(f"{c.count(breached)} past SLA target")

    with st.container(border=True):
        stats = domain.agreement_stats()
        if stats["total"]:
            c.stat_block(
                "Agreement statistics", f"{c.count(stats['total'])} reviewed",
                [
                    ("Agreed with AI", f"{stats['agreement_pct']}%", "var(--tc-low)"),
                    ("Overridden", stats["overridden"], "var(--tc-muted)"),
                ],
            )
        else:
            c.stat_block("Agreement statistics", "No reviews yet", [("Reviewed", 0, "var(--tc-muted)")])
            st.caption("Confirm or override a ticket to start building this.")


# --- Navigation entry points --------------------------------------------------

def _open_detail_or(render_list, belongs_here=None) -> None:
    """Show the detail view when a ticket is open, otherwise the list.

    ``belongs_here`` decides whether *this* destination is willing to open a
    given ticket inline. Both queue pages share the open-tab state, so without
    it, opening a ticket on Tickets and then clicking "Safety-net escalations"
    left the agent looking at that same ticket under the escalation heading —
    including tickets whose own Safety net field read "Not triggered". The page
    carrying this project's headline correctness claim was showing a ticket the
    net never touched, and the rail gave no clue you had arrived somewhere.
    Found by /qa (ISSUE-003).

    Passing None means "this page will open anything", which is right for
    Tickets: it is the full queue, so every ticket genuinely belongs to it.
    """
    tickets = domain.load_tickets()
    active = state.find_ticket(tickets, state.active_ticket_id())
    if active is not None and (belongs_here is None or belongs_here(active)):
        ticket_detail.render(active, tickets)
    else:
        render_list(tickets)


def render() -> None:
    _open_detail_or(
        lambda tickets: render_queue(
            tickets,
            "Tickets",
            "Every open ticket, pre-sorted by urgency.",
            key_prefix="tickets",
        )
    )


def render_safety_net() -> None:
    """Only tickets the Critical-class safety net escalated.

    This is the project's most important correctness rule, so it gets its own
    destination rather than being buried behind a checkbox — and, since this is
    the page about the mechanism, the explanation of how the scorer assigns
    priority lives here too, in a collapsed expander above the queue.

    Collapsed by default deliberately. An agent working this page wants the
    tickets; the explanation is for the first visit and for anyone asking why a
    ticket was escalated, so it must be one click away but never in the way.
    """
    def _list(tickets: List[Dict]) -> None:
        escalated = [t for t in tickets if t.get("safety_net_triggered")]
        with st.expander("How priority is decided, and what the safety net does", expanded=False):
            c.scorer_explainer(
                domain.scorer_reference(),
                domain.safety_net_stats(),
                # A hard trigger with almost no other keyword mass, so the example
                # shows the net doing the one thing it exists to do: 28 + 30 = 58
                # is Medium, and it still leaves as High. This is Jordan's billing
                # incident in one sentence (PROJECT_PLAN.md §1).
                domain.scorer_worked_example("The billing system is down."),
            )
        render_queue(
            escalated,
            "Safety-net escalations",
            "Tickets force-escalated to at least High by a hard-priority signal.",
            key_prefix="safetynet",
            empty_message="No safety-net escalations in this batch.",
        )

    # Only escalated tickets open inline here. Anything else opened elsewhere
    # falls through to this page's own list rather than hijacking it.
    _open_detail_or(_list, belongs_here=lambda t: bool(t.get("safety_net_triggered")))
