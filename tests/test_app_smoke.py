"""Smoke tests for the Streamlit console.

Runs the app in Streamlit's simulated harness (no browser) and asserts it renders
without raising — enough to catch layout/API breakage in CI without a live batch
or API key.

Note on ``AppTest``: the console is a multipage app built with ``st.navigation``.
``AppTest.from_file("app.py")`` traverses it correctly and runs the default page.
Individual views are exercised with ``AppTest.from_string`` so the view module is
imported normally — ``AppTest.from_function`` re-executes a function's source
without its module globals and fails with spurious ``NameError``s.

The console renders most of its chrome as markup via ``st.html``, which AppTest
exposes through ``at.get("html")`` rather than ``at.markdown``.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

TICKETS_VIEW = "from ui.views import tickets\ntickets.render()\n"


def _html(at) -> str:
    """All html element bodies rendered by the app, concatenated."""
    return "\n".join(el.body for el in at.get("html"))


def test_app_runs_without_exception():
    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception, at.exception
    # The shell renders its own app bar rather than st.title.
    assert "tc-appbar" in _html(at)


def test_sla_and_age_helpers_are_deterministic():
    from ui.domain import simulated_age_hours, sla_state

    assert simulated_age_hours("T00001") == simulated_age_hours("T00001")
    assert 0 <= simulated_age_hours("T00042") <= 48
    assert "breached" in sla_state("Critical", age_hours=10)  # 1h target, 10h old


def test_demo_context_is_stable_for_a_ticket():
    """D1 depends on this: a requester must not change between reruns."""
    from ui.demo_context import requester_for

    ticket = {"id": "T00042"}
    first, second = requester_for(ticket), requester_for(ticket)
    assert first == second
    assert first.email.endswith(".example")  # never a routable domain


# Regression: ISSUE-001 — the queue-size readout showed the full dataset size
# instead of the filtered count, so it read 800 even when a search or priority
# filter narrowed the queue to a handful.
# Found by /qa on 2026-07-24. Report:
#   .gstack/qa-reports/qa-report-localhost-8501-2026-07-24.md
# Re-written for the Zendesk-style console: the readout moved from a sidebar
# st.metric to the header chip, and the header now renders into a reserved
# placeholder specifically so it can report the post-filter count.
def test_header_count_tracks_active_filter():
    at = AppTest.from_string(TICKETS_VIEW, default_timeout=90).run()
    assert not at.exception, at.exception

    def counts(app):
        body = _html(app)
        chip = re.search(r'class="tc-chip">(\d+) in view<', body)
        section = re.search(r'class="tc-section">(\d+) tickets<', body)
        assert chip and section, "header chip / section count missing from render"
        return int(chip.group(1)), int(section.group(1))

    baseline_chip, baseline_section = counts(at)
    assert baseline_chip == baseline_section

    # Narrow the queue with a search that matches a subset.
    at.text_input[0].set_value("breach").run()
    assert not at.exception, at.exception

    chip, section = counts(at)
    # The header must agree with the list it sits above...
    assert chip == section
    # ...and the filter must actually have narrowed the set, else this test would
    # pass even with the bug present.
    assert chip < baseline_chip


# Regression: ISSUE-002 — an over-narrow filter collapsed the two-column layout.
# `render_queue` returned early from inside `with left:` when the filtered queue
# was empty, which skipped the `with right:` block entirely and took the whole
# statistics rail with it. Agreement statistics describes the review log, not the
# queue, so it must survive a filter that matches nothing.
# Found by /qa on 2026-07-28.
# Report: .gstack/qa-reports/qa-report-localhost-8501-2026-07-28.md
def test_statistics_rail_survives_an_empty_filtered_queue():
    at = AppTest.from_string(TICKETS_VIEW, default_timeout=90).run()
    assert not at.exception, at.exception
    assert "tc-stat__head" in _html(at), "rail missing before filtering"

    at.text_input[0].set_value("zzqqxx-no-ticket-matches-this").run()
    assert not at.exception, at.exception

    body = _html(at)
    assert "tc-empty" in body, "empty state should render"
    assert "tc-stat__head" in body, "statistics rail must survive an empty queue"
    assert re.search(r'class="tc-chip">0 in view<', body), "header should report zero"


# Regression: ISSUE-006 — the console rendered no heading elements at all.
# Replacing st.title/st.subheader with styled <div>/<p> markup left the page with
# h1:0 h2:0, so screen-reader users had no outline to navigate by. The classes
# carry the look; the tags have to carry the meaning.
# Found by /qa on 2026-07-28.
# Report: .gstack/qa-reports/qa-report-localhost-8501-2026-07-28.md
def test_views_render_a_heading_outline():
    at = AppTest.from_string(TICKETS_VIEW, default_timeout=90).run()
    assert not at.exception, at.exception
    body = _html(at)
    assert '<h1 class="tc-appbar__title"' in body, "page title must be an h1"
    assert '<h2 class="tc-section"' in body, "section headings must be h2"


def test_ticket_detail_heading_outline_is_nested():
    script = (
        "from ui.views import tickets\n"
        "from ui import state, domain\n"
        "ts = domain.load_tickets()\n"
        "if ts:\n"
        "    state.open_ticket(ts[0]['id'])\n"
        "tickets.render()\n"
    )
    at = AppTest.from_string(script, default_timeout=90).run()
    assert not at.exception, at.exception
    body = _html(at)
    assert '<h1 class="tc-appbar__title"' in body
    assert '<h2 class="tc-section"' in body
    # Panels sit one level below the section they belong to.
    assert '<h3 class="tc-panel__title"' in body


# Regression: ISSUE-004 — the Queue filter listed the full QUEUE_OPTIONS enum, so
# three queues that never appear in the data (Returns and Exchanges, Sales and
# Pre-Sales, Human Resources) were selectable and always returned an empty queue
# with no explanation. Filter controls must be built from the loaded batch.
# Found by /qa on 2026-07-28.
# Report: .gstack/qa-reports/qa-report-localhost-8501-2026-07-28.md
def test_every_offered_queue_filter_matches_at_least_one_ticket():
    from ui.domain import QUEUE_OPTIONS, filter_tickets, load_tickets, queues_in_use

    tickets = load_tickets()
    if not tickets:
        pytest.skip("no data loaded")

    offered = queues_in_use()
    assert offered, "queue filter must offer something when tickets are loaded"
    # Never invent a queue the enum doesn't sanction...
    assert set(offered) <= set(QUEUE_OPTIONS)
    # ...and never offer one the data can't satisfy.
    for queue in offered:
        assert filter_tickets(tickets, queues=[queue]), f"{queue!r} matches nothing"


# Regression: ISSUE-005 — results/evaluation.md is a standalone document, so it
# opens with an h1. Rendered raw inside the Reporting page that h1 came out
# larger than the page title above it and read as the start of a new document.
# Found by /qa on 2026-07-28.
# Report: .gstack/qa-reports/qa-report-localhost-8501-2026-07-28.md
def test_embedded_report_headings_are_demoted():
    from ui.views.dashboard import demote_headings

    src = "# Title\ntext\n## Section\n### Sub\n"
    out = demote_headings(src).splitlines()
    # Compare whole lines: "### Title" trivially *contains* "# Title", so a
    # substring check would pass even if nothing had been demoted.
    assert out[0] == "### Title"
    assert "#### Section" in out
    assert "##### Sub" in out


def test_demote_headings_skips_fenced_code():
    """A `#` comment in a shell example is not a heading."""
    from ui.views.dashboard import demote_headings

    src = "# Real heading\n\n```bash\n# just a comment\necho hi\n```\n"
    out = demote_headings(src)
    assert "### Real heading" in out
    assert "# just a comment" in out, "comment inside a fence must be untouched"


def test_demote_headings_caps_at_h6():
    from ui.views.dashboard import demote_headings

    assert demote_headings("##### Deep").startswith("######")
    assert "#######" not in demote_headings("##### Deep")


# Regression: ISSUE-008 — the requester/subject divider was a literal "|" text
# node, so a long subject that wrapped left the separator stranded on the line
# above, pointing at nothing. It is now a CSS border carried by the subject.
# Found by /qa on 2026-07-28.
# Report: .gstack/qa-reports/qa-report-localhost-8501-2026-07-28.md
def test_ticket_row_has_no_literal_separator_text():
    at = AppTest.from_string(TICKETS_VIEW, default_timeout=90).run()
    assert not at.exception, at.exception
    body = _html(at)
    assert 'class="tc-row__name"' in body, "rows should have rendered"
    assert '<span class="tc-row__sep">|</span>' not in body, (
        "name/subject divider must be a CSS border, not a text node"
    )


# Dark mode is implemented by appending a second stylesheet that re-declares the
# :root custom properties, because Streamlit 1.39 has no runtime theming API and
# does not execute <script> passed through st.markdown. These two tests pin both
# halves of that mechanism: the swap happens, and the components are actually
# reachable by it.
def test_dark_mode_appends_the_dark_stylesheet():
    script = (
        "from ui import theme\n"
        "theme.inject_css()\n"
        "from ui.views import settings\n"
        "settings.render()\n"
    )
    at = AppTest.from_string(script, default_timeout=90).run()
    assert not at.exception, at.exception

    light_css = "\n".join(m.body for m in at.markdown)
    assert "--tc-canvas: #141A1F" not in light_css, "dark overrides leaked into light mode"

    at.toggle[0].set_value(True).run()
    assert not at.exception, at.exception
    dark_css = "\n".join(m.body for m in at.markdown)
    assert "--tc-canvas: #141A1F" in dark_css, "dark stylesheet was not appended"
    # Streamlit's own shell must be re-skinned too; config.toml is read once at
    # server start and would otherwise keep the app background light.
    assert '[data-testid="stAppViewContainer"]' in dark_css


def test_priority_markup_uses_css_variables_not_literal_hex():
    """Inline hex would survive a theme swap and leave pills light on a dark card."""
    from ui.components import priority_pill_html, score_bar_html
    from ui.theme import priority

    pill = priority_pill_html("Critical")
    assert "var(--tc-critical)" in pill and "var(--tc-critical-tint)" in pill
    assert "#CC3340" not in pill and "#FCEDEE" not in pill

    bar = score_bar_html(90, priority("Critical").var_color)
    assert "var(--tc-critical)" in bar

    # The literal values still exist on the token, because Altair renders to SVG
    # through a Vega-Lite spec and cannot resolve a CSS variable.
    assert priority("Critical").color == "#CC3340"


# The Dashboard's integrity panel is the one place the project admits what its
# data cannot support. It must be computed from the loaded batch, not transcribed
# from a one-off analysis, or it will quietly go stale when the batch changes.
def test_dashboard_integrity_panel_is_computed_from_the_batch():
    from ui import domain

    facts = domain.data_integrity()
    assert facts["total"] > 0

    si = facts["subject_independence"]
    # Independence: chi-square at or below its degrees of freedom, effect size ~0.
    assert si["chi2"] <= si["dof"] * 1.5, "subject/label association is stronger than expected"
    assert si["cramers_v"] < 0.15, f"Cramer's V unexpectedly high: {si['cramers_v']}"

    # The timestamp columns must still be recognised as incoherent, since two
    # charts are omitted from the product on the strength of it.
    assert facts["timestamp_pairs"] > 0
    assert facts["timestamp_inverted_rate"] > 0.2, (
        "resolution-before-response rate collapsed — if the data was fixed, "
        "the omitted resolution-time chart should be reconsidered"
    )

    assert 0 < facts["csat"]["coverage"] < 1, "CSAT should cover only closed tickets"


# Regression: the Dashboard crashed with
#   AttributeError: 'NoneType' object has no attribute 'notna'
# against a batch generated before the dataset swap. `frame.get(missing)` returns
# None, and `pd.to_datetime(None)` returns None rather than an empty Series, so
# the timestamp check blew up and took the whole page with it. Found by loading
# the running app in a browser — every unit test passed, because they all ran
# against a current batch.
def test_dashboard_survives_a_pre_swap_batch(monkeypatch):
    from ui import domain

    old_style = [
        {"id": "T1", "subject": "Login broken", "body": "b", "category": "High",
         "true_priority": "high", "score": 70, "tags": []},
        {"id": "T2", "subject": "Invoice query", "body": "b", "category": "Low",
         "true_priority": "low", "score": 20, "tags": []},
    ]
    monkeypatch.setattr(domain, "load_tickets", lambda: old_style)
    domain.tickets_frame.clear()

    try:
        frame = domain.tickets_frame()
        # Analytics columns are guaranteed present so chart code can index them.
        for column in domain.ANALYTICS_COLUMNS:
            assert column in frame.columns

        facts = domain.data_integrity()          # must not raise
        assert facts["timestamp_pairs"] == 0
        assert facts["timestamp_inverted_rate"] == 0.0
        assert domain.count_by("channel") == {}   # no data, not a crash
        assert domain.csat_summary()["rated"] == 0
    finally:
        domain.tickets_frame.clear()


def test_dashboard_renders_kpis_and_integrity_panel():
    at = AppTest.from_string(
        "from ui.views import dashboard\ndashboard.render()\n", default_timeout=180
    ).run()
    assert not at.exception, at.exception
    body = _html(at)
    assert body.count("tc-kpi__value") == 5, "expected five KPI tiles"
    assert "tc-integrity" in body, "data-integrity panel must render"
    # Neither omitted chart may reappear without the data supporting it.
    assert "Avg. Resolution Time" not in body
    assert "resolution time" in body.lower(), "the omission must be explained, not silent"


# Regression: ISSUE-009 — the Settings "Preferences" controls did nothing.
# Both widgets bound their `key` directly to the preference key. Streamlit
# garbage-collects session_state entries whose widget was not rendered in the
# current script run, and these widgets only exist on the Settings page, so the
# value was discarded the moment the agent navigated away: the preference never
# reached Home or Tickets, and returning to Settings showed it reset. The
# selectbox did not even hold its value on Settings itself.
# Found by /qa on 2026-07-29 via click-through navigation in a browser.
# Report: .gstack/qa-reports/qa-report-localhost-8562-2026-07-29.md
def test_preference_keys_are_not_widget_keys():
    """The durable key must never be a widget key, or Streamlit will collect it."""
    from pathlib import Path

    from ui import state

    assert state.ATTENTION_LIMIT_KEY != state.W_ATTENTION_LIMIT
    assert state.DEFAULT_SORT_KEY != state.W_DEFAULT_SORT
    # The widget keys are the ones bound in ui/views/settings.py. If a future edit
    # rebinds a widget to the durable key, this pairing check is what catches it.
    settings_src = (
        Path(__file__).resolve().parents[1] / "ui" / "views" / "settings.py"
    ).read_text(encoding="utf-8")
    assert "key=state.W_ATTENTION_LIMIT" in settings_src
    assert "key=state.W_DEFAULT_SORT" in settings_src
    assert "key=state.ATTENTION_LIMIT_KEY" not in settings_src
    assert "key=state.DEFAULT_SORT_KEY" not in settings_src


def test_persist_callbacks_copy_widget_value_to_durable_key():
    from ui import state

    script = (
        "import streamlit as st\n"
        "from ui import state\n"
        "st.session_state[state.W_ATTENTION_LIMIT] = 12\n"
        "state.persist_attention_limit()\n"
        "st.session_state[state.W_DEFAULT_SORT] = 'Highest score'\n"
        "state.persist_default_sort()\n"
        "st.write(f'limit={state.attention_limit()} sort={state.default_sort()}')\n"
    )
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, at.exception
    assert at.session_state[state.ATTENTION_LIMIT_KEY] == 12
    assert at.session_state[state.DEFAULT_SORT_KEY] == "Highest score"
    body = "\n".join(str(m.value) for m in at.markdown)
    assert "limit=12 sort=Highest score" in body, body


def test_preferences_survive_a_run_without_the_settings_widgets():
    """The real failure mode: read the preference on a page that has no widget."""
    script = (
        "import streamlit as st\n"
        "from ui import state\n"
        "# Simulate Settings having run earlier and persisted the choice...\n"
        "st.session_state.setdefault(state.ATTENTION_LIMIT_KEY, 11)\n"
        "# ...then a page that renders no Settings widget at all reads it.\n"
        "st.write(f'limit={state.attention_limit()}')\n"
    )
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, at.exception
    body = "\n".join(str(m.value) for m in at.markdown)
    assert "limit=11" in body, body


# Regression: ISSUE-010 — the default page carried url_path="home", but Streamlit
# serves whichever page is default=True at "/" and never registers its url_path.
# So /home was dead config claiming a route the router did not know, and hitting
# it produced Streamlit's "page does not seem to exist" dialog. /home is the most
# guessable URL in the app, so the dialog was reachable by typing.
# Found by /qa on 2026-07-29.
# Report: .gstack/qa-reports/qa-report-localhost-8562-2026-07-29.md
def test_default_page_declares_no_url_path():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    # Find the st.Page(...) call carrying default=True and assert it has no
    # url_path. Matching on the call text keeps this readable and specific.
    calls = re.findall(r"st\.Page\((?:[^()]|\([^()]*\))*\)", src, re.DOTALL)
    default_calls = [c for c in calls if "default=True" in c]
    assert len(default_calls) == 1, f"expected exactly one default page, got {len(default_calls)}"
    assert "url_path" not in default_calls[0], (
        "the default page must not declare a url_path — Streamlit serves it at '/' "
        "and never registers the path, so declaring one claims a route that 404s"
    )


def test_every_view_renders():
    """Each navigation destination renders without raising."""
    calls = {
        "home": "home.render()",
        "tickets": "tickets.render()",
        "safety_net": "tickets.render_safety_net()",
        "following": "following.render()",
        "completed": "completed.render()",
        "dashboard": "dashboard.render()",
        "settings": "settings.render()",
    }
    imports = "from ui.views import home, tickets, following, completed, dashboard, settings\n"
    for name, call in calls.items():
        at = AppTest.from_string(imports + call, default_timeout=90).run()
        assert not at.exception, f"{name} raised: {at.exception}"


def test_ticket_detail_renders_with_a_ticket_open():
    script = (
        "from ui.views import tickets\n"
        "from ui import state, domain\n"
        "ts = domain.load_tickets()\n"
        "if ts:\n"
        "    state.open_ticket(ts[0]['id'])\n"
        "tickets.render()\n"
    )
    at = AppTest.from_string(script, default_timeout=90).run()
    assert not at.exception, at.exception

    body = _html(at)
    # The internal note carries the AI rationale — the one panel where the
    # reference layout and this project's real data line up exactly.
    assert "tc-note" in body
    # Simulated panels must always be labelled (D1).
    assert "tc-pill--demo" in body
