"""Settings — appearance, account options, and full disclosure on simulated data.

The disclosure section is not decoration. D1 traded a visible "simulated" badge
for a layout that matches the reference, and this page is where that promise is
paid in full: every simulated field, named, in one place.

## On which controls actually do something

This console has no auth layer, no mail path, and one hard-coded agent. Rather
than render a page of realistic-looking switches that persist nothing, each
control here is one of two things:

* **Real** — Dark mode, the Home attention-list size, and the default queue sort
  are session-scoped preferences that genuinely change the UI.
* **Explained** — Notifications has no delivery channel behind it and says so.
  Security is presented as a read-only statement of how the build actually
  handles credentials and data, which is more useful to a reviewer than a
  disabled two-factor toggle would be.

That split is the same one `docs/UI_SPEC.md` applies to the composer and the
macro button, and the same one the rail's profile menu applies to Log out.
"""

from __future__ import annotations

import streamlit as st

from ui import components as c
from ui import domain, prefs, state, theme


def render() -> None:
    c.app_bar("Settings", "Appearance, account options, and what's real versus simulated.")

    left, right = st.columns([1, 1], gap="medium")

    with left:
        _appearance()
        _notifications()
        _data_source()

    with right:
        _security()
        _preferences()
        _sla_targets()

    c.section("Data provenance")
    st.caption(
        "The single most important thing on this page: which numbers you can "
        "trust, and which exist only so the layout reads correctly."
    )
    prov_left, prov_right = st.columns([1, 1], gap="medium")
    with prov_left:
        _real_data()
    with prov_right:
        _simulated_data()


# --- Appearance ---------------------------------------------------------------

def _appearance() -> None:
    with st.container(border=True):
        c.panel_title("Appearance")
        dark = st.toggle(
            "Dark mode",
            value=theme.is_dark(),
            key="settings_dark_mode",
            help="Switches the workspace to a dark palette. Applies immediately.",
        )
        if dark != theme.is_dark():
            theme.set_dark(dark)
            st.rerun()

        st.caption(
            "The navigation rail stays dark teal in both themes — that is the "
            "shell colour the console is modelled on, not a light-mode artifact."
        )
        st.caption(
            "Scoped to this browser session. Streamlit 1.39 reads `config.toml` "
            "once at server start and has no runtime theming API, so the swap is "
            "done by appending a second stylesheet rather than persisting a "
            "preference server-side."
        )


# --- Account ------------------------------------------------------------------

def _security() -> None:
    with st.container(border=True):
        c.panel_title("Security")
        st.markdown(
            "- **No authentication layer.** The console has no login, no session, "
            "and no user directory. Anyone who can reach the port can use it.\n"
            "- **No credentials are stored.** The only secret this project can "
            "use is `ANTHROPIC_API_KEY`, read from the environment at batch time "
            "and never written to disk or into `classified_tickets.json`.\n"
            "- **No outbound network calls from the UI.** The Streamlit app reads "
            "local files only. The Claude call happens offline, in "
            "`python -m src.batch_classify --with-rationale`.\n"
            "- **That call sends no identity.** Prompts are built from an "
            "allowlist (`src/sanitize.py`) — ticket subject and body plus the "
            "scorer's verdict — and the surviving text has emails, phone "
            "numbers, card-length digit runs, and the requester's own name "
            "redacted out. Checked across all 8,469 tickets: zero leaks.\n"
            "- **Usage statistics are off** (`gatherUsageStats = false`), so a "
            "reviewer running this locally phones nothing home."
        )
        st.caption(
            "Stated as facts rather than offered as switches: none of this is "
            "configurable in a portfolio build, and a disabled 2FA toggle would "
            "imply an account system that does not exist."
        )


def _notifications() -> None:
    """Notifications, stated rather than switched.

    This panel used to render three toggles that were `disabled=True` forever,
    under a caption explaining they would never do anything. Three controls whose
    entire purpose was to announce their own uselessness.

    Cut in favour of the sentence. A control that cannot be operated has not
    earned its pixels, and the Security panel below already does exactly this:
    it states how the build behaves instead of offering switches that do not
    switch. This also removes three controls from the keyboard-focus contract,
    which is the cheapest possible way to finish that work.
    """
    with st.container(border=True):
        c.panel_title("Notifications")
        st.markdown(
            "**There are none, and that is deliberate.** This project triages "
            "tickets. It has no outbound mail path, no scheduler, and no address "
            "to send to, so there is nothing to configure here."
        )
        st.caption(
            "A Critical ticket surfaces at the top of Home and in Safety-net "
            "escalations. That is the whole notification system."
        )


def _preferences() -> None:
    with st.container(border=True):
        c.panel_title("Preferences")

        # Each widget owns its own `_w_*` key; an on_change callback copies the
        # value into the durable preference key. Binding a widget straight to the
        # durable key silently did nothing, because Streamlit collects widget
        # state for widgets absent from the current run, so the value vanished on
        # navigation and never reached Home or Tickets (ISSUE-009).
        #
        # Neither widget is given a `value=` or `index=`, and that absence is the
        # fix for ISSUE-002. Passing one recomputed from the durable key looked
        # harmless and re-mounted the widget on every rerun, which dropped
        # keyboard focus: from 3, five Right presses to reach 8 produced
        # 4, 4, 4, 4, 4 — the first landed, then focus fell to <body>.
        #
        # `bind` seeds the widget key only when it is absent, which is exactly
        # when Streamlit collected it. So the preference survives navigation
        # without the widget ever being handed a changing prop.
        prefs.bind(
            state.W_ATTENTION_LIMIT, state.ATTENTION_LIMIT_KEY,
            state.DEFAULT_ATTENTION_LIMIT, coerce=prefs.clamp_attention_limit,
        )
        st.slider(
            "Tickets shown on Home",
            min_value=prefs.ATTENTION_LIMIT_MIN, max_value=prefs.ATTENTION_LIMIT_MAX,
            key=state.W_ATTENTION_LIMIT,
            on_change=prefs.persist,
            args=(state.W_ATTENTION_LIMIT, state.ATTENTION_LIMIT_KEY),
            help="How many tickets the Home 'Needs attention now' list shows.",
        )
        prefs.bind(
            state.W_DEFAULT_SORT, state.DEFAULT_SORT_KEY, domain.SORT_OPTIONS[0],
            coerce=lambda v: v if v in domain.SORT_OPTIONS else domain.SORT_OPTIONS[0],
        )
        st.selectbox(
            "Default queue sort",
            domain.SORT_OPTIONS,
            key=state.W_DEFAULT_SORT,
            on_change=prefs.persist,
            args=(state.W_DEFAULT_SORT, state.DEFAULT_SORT_KEY),
            help="Which sort the Tickets view opens with.",
        )
        st.caption(
            "Both apply immediately and last for this session. The queue sort "
            "sets what Tickets opens with; the queue's own Sort control still "
            "overrides it per-visit."
        )
        st.caption(
            "A full page reload starts a new Streamlit session and returns these "
            "to their defaults. Dark mode survives a reload because it is mirrored "
            "into the URL; these are not, since a shared link carrying someone "
            "else's list length would be surprising rather than useful."
        )


# --- Data ---------------------------------------------------------------------

def _data_source() -> None:
    source = domain.active_data_source()
    with st.container(border=True):
        c.panel_title("Data source")
        c.field("Loaded file", source.name if source else "none found")
        c.field("Tickets", f"{len(domain.load_tickets()):,}")
        c.field("Override log", "present" if domain.OVERRIDE_LOG.exists() else "not created yet")
        if source and source.name.endswith("sample.json"):
            st.caption(
                "Running on the committed demo sample. Run "
                "`python -m src.batch_classify` for the full batch."
            )


def _sla_targets() -> None:
    with st.container(border=True):
        c.panel_title("SLA targets")
        for cat, hours in domain.SLA_HOURS.items():
            c.field(cat.value, f"{hours}h")
        st.caption(
            "Ticket age is derived from a hash of the ticket id. This dataset's "
            "own timestamps are unusable — 49% of closed tickets record a "
            "resolution before their first response — so the countdown is a "
            "stable demo clock rather than a reading of the data. See the "
            "Dashboard's data-integrity panel."
        )


def _real_data() -> None:
    with st.container(border=True):
        c.panel_title("Real data")
        st.markdown(
            "- Priority, urgency score, and category\n"
            "- Matched keyword signals\n"
            "- Critical-class safety-net state\n"
            "- The AI rationale and suggested queue\n"
            "- Ticket subject, body, and tags\n"
            "- Dataset ground-truth priority label (four levels, incl. Critical)\n"
            "- **Requester name and email**\n"
            "- **Ticket status, channel, type, and product**\n"
            "- **Customer satisfaction rating** (closed tickets only, 32.7% coverage)\n"
            "- Your confirm/override decisions (`results/override_log.csv`)\n"
            "- Agreement statistics computed from that log"
        )
        st.caption(
            "The bold entries became real with the dataset swap — the previous "
            "dataset had no requester identity, status, channel, or CSAT column, "
            "so those panels were simulated."
        )
        st.caption(
            "⚠️ Real individually, not as a pair: only 1.0% of rows have an email "
            "whose local part relates to the customer name, so a ticket can show "
            "a real name beside a real but unrelated address. The requester panel "
            "says so where it shows them."
        )


def _simulated_data() -> None:
    with st.container(border=True):
        c.panel_title("Simulated for demonstration", badge=True)
        st.markdown(
            "- Requester phone, organization, city, local time, and tenure\n"
            "- Agent reply turns in the conversation thread\n"
            "- Interaction history\n"
            "- Ticket age and the SLA countdown"
        )
        st.caption(
            "These fields have no source column in the dataset. They are derived "
            "deterministically from the ticket id so they stay stable across "
            "reruns, and none of them influences triage. Every panel fed by them "
            "carries a `simulated` badge."
        )
        st.caption(
            "Not shown anywhere in this console: average resolution time and "
            "ticket volume over time. The dataset's timestamps cannot support "
            "them honestly, so they were cut rather than faked."
        )
