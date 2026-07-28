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


def test_every_view_renders():
    """Each navigation destination renders without raising."""
    calls = {
        "home": "home.render()",
        "tickets": "tickets.render()",
        "safety_net": "tickets.render_safety_net()",
        "following": "following.render()",
        "completed": "completed.render()",
        "reporting": "reporting.render()",
        "settings": "settings.render()",
    }
    imports = "from ui.views import home, tickets, following, completed, reporting, settings\n"
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
