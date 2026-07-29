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

# Settings-page preferences.
#
# Each preference has TWO keys, and the split is load-bearing. Streamlit garbage-
# collects session_state entries whose widget was not rendered during the current
# script run. The Settings widgets only exist on the Settings page, so binding a
# widget's `key` directly to the preference meant the value was discarded the
# moment the agent navigated anywhere else: the preference never reached Home or
# Tickets, and returning to Settings showed it reset to the default. Found by /qa
# (ISSUE-009) — every unit test passed, because none of them navigated.
#
# So the widget owns the `_W_*` key, and an on_change callback copies its value
# into the durable `*_KEY`. A key that is never a widget key is never collected.
ATTENTION_LIMIT_KEY = "pref_attention_limit"
DEFAULT_SORT_KEY = "pref_default_sort"
W_ATTENTION_LIMIT = "_w_attention_limit"
W_DEFAULT_SORT = "_w_default_sort"

MAX_TABS = 6  # Zendesk caps the visible tab strip too; past this the oldest closes

DEFAULT_ATTENTION_LIMIT = 6


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
    return int(st.session_state.get(ATTENTION_LIMIT_KEY, DEFAULT_ATTENTION_LIMIT))


def default_sort() -> str:
    """Which sort the Tickets view opens with."""
    from ui.domain import SORT_OPTIONS  # local import avoids a cycle at module load

    value = st.session_state.get(DEFAULT_SORT_KEY, SORT_OPTIONS[0])
    return value if value in SORT_OPTIONS else SORT_OPTIONS[0]


def persist_attention_limit() -> None:
    """Copy the Settings slider's value into the durable key. See the key block."""
    if W_ATTENTION_LIMIT in st.session_state:
        st.session_state[ATTENTION_LIMIT_KEY] = int(st.session_state[W_ATTENTION_LIMIT])


def persist_default_sort() -> None:
    """Copy the Settings selectbox's value into the durable key. See the key block."""
    if W_DEFAULT_SORT in st.session_state:
        st.session_state[DEFAULT_SORT_KEY] = st.session_state[W_DEFAULT_SORT]


def set_last_action(message: str) -> None:
    st.session_state[_LAST_ACTION] = message


def pop_last_action() -> Optional[str]:
    """Read and clear the toast, so a confirmation doesn't persist across views."""
    return st.session_state.pop(_LAST_ACTION, None)


def find_ticket(tickets: List[Dict], ticket_id: Optional[str]) -> Optional[Dict]:
    if ticket_id is None:
        return None
    return next((t for t in tickets if t["id"] == ticket_id), None)
