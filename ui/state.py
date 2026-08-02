"""Session-state helpers.

Streamlit reruns the whole script on every interaction, so anything that must
survive a click lives in ``st.session_state``. Keeping the keys behind functions
means no view has to remember whether a key has been initialised yet.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import streamlit as st

from ui import prefs

_OPEN_TABS = "open_ticket_ids"   # ticket ids currently open as tabs
_ACTIVE = "active_ticket_id"     # which tab is focused
_FOLLOWING = "following_ids"     # "Shared work → Following"
_LAST_ACTION = "last_action"     # confirm/override toast text

# Settings-page preferences.
#
# The two-key split and the reasoning behind it now live in `ui/prefs.py`, which
# owns every durable preference on one pattern. This module re-exports the names
# so existing call sites and tests keep working, and so `ui.state` stays the
# place a view looks for session concerns generally.
#
# The split is still load-bearing, and the short version is: Streamlit collects
# session_state entries whose widget was not rendered in the current run, so the
# durable key must never be a widget key (ISSUE-009). The newer half of the rule
# is that the widget must never be handed a `value=`/`index=` either, or it
# re-mounts on every rerun and drops keyboard focus (ISSUE-002). See prefs.py.
ATTENTION_LIMIT_KEY = prefs.ATTENTION_LIMIT
DEFAULT_SORT_KEY = prefs.DEFAULT_SORT
W_ATTENTION_LIMIT = prefs.W_ATTENTION_LIMIT
W_DEFAULT_SORT = prefs.W_DEFAULT_SORT

MAX_TABS = 6  # Zendesk caps the visible tab strip too; past this the oldest closes

DEFAULT_ATTENTION_LIMIT = prefs.DEFAULT_ATTENTION_LIMIT


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


def attention_limit() -> int:
    """How many tickets Home's 'Needs attention now' list shows."""
    return prefs.attention_limit()


def default_sort() -> str:
    """Which sort the Tickets view opens with."""
    from ui.domain import SORT_OPTIONS  # local import avoids a cycle at module load

    return prefs.default_sort(SORT_OPTIONS)


def persist_attention_limit() -> None:
    """Copy the Settings slider's value into the durable key. See ``ui/prefs.py``."""
    prefs.persist(W_ATTENTION_LIMIT, ATTENTION_LIMIT_KEY)


def persist_default_sort() -> None:
    """Copy the Settings selectbox's value into the durable key. See ``ui/prefs.py``."""
    prefs.persist(W_DEFAULT_SORT, DEFAULT_SORT_KEY)


def set_last_action(message: str) -> None:
    st.session_state[_LAST_ACTION] = message


def pop_last_action() -> Optional[str]:
    """Read and clear the toast, so a confirmation doesn't persist across views."""
    return st.session_state.pop(_LAST_ACTION, None)


def find_ticket(tickets: List[Dict], ticket_id: Optional[str]) -> Optional[Dict]:
    if ticket_id is None:
        return None
    return next((t for t in tickets if t["id"] == ticket_id), None)
