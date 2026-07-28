"""Session-state helpers.

Streamlit reruns the whole script on every interaction, so anything that must
survive a click lives in ``st.session_state``. Keeping the keys behind functions
means no view has to remember whether a key has been initialised yet.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import streamlit as st

_OPEN_TABS = "open_ticket_ids"   # ticket ids currently open as tabs
_ACTIVE = "active_ticket_id"     # which tab is focused
_FOLLOWING = "following_ids"     # "Shared work → Following"
_LAST_ACTION = "last_action"     # confirm/override toast text

MAX_TABS = 6  # Zendesk caps the visible tab strip too; past this the oldest closes


def _init() -> None:
    st.session_state.setdefault(_OPEN_TABS, [])
    st.session_state.setdefault(_FOLLOWING, set())
    st.session_state.setdefault(_ACTIVE, None)


def open_tabs() -> List[str]:
    _init()
    return st.session_state[_OPEN_TABS]


def open_ticket(ticket_id: str) -> None:
    """Open a ticket as a tab and focus it. Re-opening an open ticket just focuses it."""
    _init()
    tabs = st.session_state[_OPEN_TABS]
    if ticket_id not in tabs:
        tabs.append(ticket_id)
        if len(tabs) > MAX_TABS:
            tabs.pop(0)
    st.session_state[_ACTIVE] = ticket_id


def close_ticket(ticket_id: str) -> None:
    _init()
    tabs = st.session_state[_OPEN_TABS]
    if ticket_id in tabs:
        tabs.remove(ticket_id)
    if st.session_state[_ACTIVE] == ticket_id:
        st.session_state[_ACTIVE] = tabs[-1] if tabs else None


def active_ticket_id() -> Optional[str]:
    _init()
    return st.session_state[_ACTIVE]


def set_active(ticket_id: Optional[str]) -> None:
    _init()
    st.session_state[_ACTIVE] = ticket_id


def following() -> set:
    _init()
    return st.session_state[_FOLLOWING]


def toggle_following(ticket_id: str) -> bool:
    """Star/unstar a ticket. Returns the new state."""
    ids = following()
    if ticket_id in ids:
        ids.remove(ticket_id)
        return False
    ids.add(ticket_id)
    return True


def set_last_action(message: str) -> None:
    st.session_state[_LAST_ACTION] = message


def pop_last_action() -> Optional[str]:
    """Read and clear the toast, so a confirmation doesn't persist across views."""
    return st.session_state.pop(_LAST_ACTION, None)


def find_ticket(tickets: List[Dict], ticket_id: Optional[str]) -> Optional[Dict]:
    if ticket_id is None:
        return None
    return next((t for t in tickets if t["id"] == ticket_id), None)
