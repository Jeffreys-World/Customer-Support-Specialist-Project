"""Shared work → Following.

The reference has "CC'd" and "Following" here. CC'd needs a participant list the
dataset doesn't have, so this ships the one that can be backed by real state: the
tickets the agent has starred this session.
"""

from __future__ import annotations

from ui import domain, state
from ui.views.tickets import render_queue


def render() -> None:
    tickets = domain.load_tickets()
    active = state.find_ticket(tickets, state.active_ticket_id())
    if active is not None:
        from ui.views import ticket_detail
        ticket_detail.render(active, tickets)
        return

    followed = [t for t in tickets if t["id"] in state.following()]
    render_queue(
        followed,
        "Following",
        "Tickets you're watching. Star one from its detail view to add it.",
        key_prefix="following",
        empty_message="You're not following any tickets yet.",
    )
