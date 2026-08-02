"""Shared work → Following.

The reference has "CC'd" and "Following" here. CC'd needs a participant list the
dataset doesn't have, so this ships the one that can be backed by real state: the
tickets the agent has starred this session.
"""

from __future__ import annotations

from ui import state
from ui.views.tickets import open_detail_or, render_queue


def render() -> None:
    def _list(tickets) -> None:
        followed = [t for t in tickets if t["id"] in state.following()]
        render_queue(
            followed,
            "Following",
            "Tickets you're watching. Star one from its detail view to add it.",
            key_prefix="following",
            empty_message="You're not following any tickets yet.",
        )

    # Only a followed ticket opens inline here. This page kept its own copy of
    # the open-detail branch, so the ISSUE-003 fix that taught Safety-net
    # escalations to refuse foreign tickets never reached it: opening any ticket
    # on Tickets and then clicking "Following" showed that ticket under the
    # Following heading, star or no star, while the tickets actually being
    # watched stayed hidden. Found by /qa (ISSUE-101).
    open_detail_or(_list, belongs_here=lambda t: t["id"] in state.following())
