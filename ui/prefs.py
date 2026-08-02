"""One persistence pattern for every durable preference.

This module is the base of the ``ui`` import graph: it imports nothing from
``ui``, so :mod:`ui.theme` and :mod:`ui.state` can both depend on it without the
local-import dodges those two files used to need.

## Why a preference needs two keys

Streamlit garbage-collects ``session_state`` entries whose widget was not
rendered during the current script run. The Settings widgets only exist on the
Settings page, so binding a widget's ``key`` straight to the preference meant the
value was discarded the moment the agent navigated anywhere else. Found by /qa as
ISSUE-009.

So every preference has a **durable key**, which is never a widget key and
therefore never collected, and a **widget key**, which the widget owns.

## Why the widget must NOT be given a value

The first fix for the above kept ``value=`` / ``index=`` on the widget,
recomputed from the durable key. That reintroduced a different bug (ISSUE-002):
on every rerun Streamlit saw a changed ``value`` prop and re-mounted the widget
instead of updating it, which **dropped keyboard focus**. Measured in the
browser: starting at 3 and pressing Right five times to reach 8 produced
``4, 4, 4, 4, 4`` — the first press landed, then focus fell to ``<body>`` and
every later keystroke went nowhere.

The shape that works is:

    seed the widget key ONCE (bind), then never pass value/index again

``bind`` writes the widget key only when it is absent, which is exactly the
moment Streamlit collected it, so navigating away and back restores the
preference without the widget ever being handed a changing prop.

    ┌─────────────┐  bind (only if absent)   ┌────────────┐
    │ durable key │ ───────────────────────▶ │ widget key │
    │  pref_*     │ ◀─────────────────────── │   _w_*     │
    └─────────────┘   persist (on_change)    └────────────┘
       survives                                 collected when
       navigation                               not rendered
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import streamlit as st

# --- Durable keys. Never a widget key. -----------------------------------------
THEME = "ui_theme"
ATTENTION_LIMIT = "pref_attention_limit"
DEFAULT_SORT = "pref_default_sort"

# --- Widget keys. Owned by the widget, seeded by `bind`. -----------------------
W_ATTENTION_LIMIT = "_w_attention_limit"
W_DEFAULT_SORT = "_w_default_sort"

DEFAULT_ATTENTION_LIMIT = 6
ATTENTION_LIMIT_MIN = 3
ATTENTION_LIMIT_MAX = 15

# The theme is mirrored here so a reload keeps it. See `is_dark`.
_THEME_PARAM = "theme"


# --- Generic read/write --------------------------------------------------------

def get(durable_key: str, default: Any = None) -> Any:
    """Read a durable preference, falling back to ``default``."""
    return st.session_state.get(durable_key, default)


def set_(durable_key: str, value: Any) -> None:
    """Write a durable preference."""
    st.session_state[durable_key] = value


# --- The widget binding pair ---------------------------------------------------

def bind(
    widget_key: str,
    durable_key: str,
    default: Any,
    coerce: Optional[Callable[[Any], Any]] = None,
) -> None:
    """Seed a widget's session entry from its durable preference, once.

    Call this immediately before rendering the widget, and then give the widget
    only its ``key`` — no ``value=``, no ``index=``. Passing both is what caused
    ISSUE-002: a changing ``value`` prop re-mounts the widget and drops focus.

    Writing only when the key is absent is what makes this safe to call on every
    rerun. Present means the widget is mid-interaction and owns the truth;
    absent means Streamlit collected it while the user was on another page, and
    the durable key is the truth.

    ``coerce`` guards the shadow paths. A durable value can be missing, out of
    range (a saved 20 against a slider that now stops at 15), or the wrong type
    (anything arriving from a query string). Streamlit raises on an out-of-range
    seed, so the coercion happens here rather than at each call site.
    """
    if widget_key in st.session_state:
        return
    value = st.session_state.get(durable_key, default)
    if coerce is not None:
        try:
            value = coerce(value)
        except (TypeError, ValueError):
            value = default
    st.session_state[widget_key] = value


def persist(widget_key: str, durable_key: str) -> None:
    """Copy a widget's value into its durable key. Use as an ``on_change``.

    Streamlit calls this with the args given to the widget, so one function
    serves every preference:

        on_change=prefs.persist, args=(W_ATTENTION_LIMIT, ATTENTION_LIMIT)
    """
    if widget_key in st.session_state:
        st.session_state[durable_key] = st.session_state[widget_key]


# --- Coercions -----------------------------------------------------------------

def clamp_attention_limit(value: Any) -> int:
    """Force any stored value into the slider's range."""
    number = int(value)
    return max(ATTENTION_LIMIT_MIN, min(ATTENTION_LIMIT_MAX, number))


def attention_limit() -> int:
    """How many tickets Home's 'Needs attention now' list shows."""
    try:
        return clamp_attention_limit(get(ATTENTION_LIMIT, DEFAULT_ATTENTION_LIMIT))
    except (TypeError, ValueError):
        return DEFAULT_ATTENTION_LIMIT


def default_sort(valid: list) -> str:
    """Which sort the Tickets view opens with.

    The caller supplies the vocabulary. Keeping the option list out of this
    module is what lets it import nothing from ``ui`` — ``SORT_OPTIONS`` lives in
    ``ui.domain``, which sits above this layer.
    """
    value = get(DEFAULT_SORT, valid[0])
    return value if value in valid else valid[0]


# --- Theme ---------------------------------------------------------------------

def is_dark() -> bool:
    """Is the console currently in dark mode?

    Session state is the live answer, with the URL as the fallback. Both are
    needed: clicking between pages keeps one Streamlit session alive, so session
    state carries the theme, but a browser refresh or an opened deep link starts
    a *new* session with empty state. Without the query-parameter fallback, a
    reload silently dropped the user back into light mode.

    Note this reads the parameter rather than trusting it: the comparison is
    ``== "dark"``, so any other value — including a hostile one — resolves to
    light rather than reaching a stylesheet.
    """
    if THEME in st.session_state:
        return st.session_state[THEME] == "dark"
    return st.query_params.get(_THEME_PARAM) == "dark"


def set_dark(enabled: bool) -> None:
    """Set the theme, mirroring it into the query string so a reload keeps it."""
    st.session_state[THEME] = "dark" if enabled else "light"
    if enabled:
        st.query_params[_THEME_PARAM] = "dark"
    elif _THEME_PARAM in st.query_params:
        del st.query_params[_THEME_PARAM]
