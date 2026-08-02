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
        # Counts carry thousands separators and the heading is singular at 1, so
        # the pattern must tolerate both (ISSUE-012).
        chip = re.search(r'class="tc-chip">([\d,]+) in view<', body)
        section = re.search(r'class="tc-section">([\d,]+) tickets?<', body)
        assert chip and section, "header chip / section count missing from render"
        return (int(chip.group(1).replace(",", "")),
                int(section.group(1).replace(",", "")))

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


# --- Type scale and motion ----------------------------------------------------

def test_type_scale_is_a_single_root_declaration():
    """Every font-size in the sheet is `rem`, which is what makes one knob work.

    A `px` or `pt` font-size would silently opt out of the root scale, so the next
    person to bump the base would find one label stubbornly unchanged.
    """
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / ".streamlit" / "styles.css").read_text(
        encoding="utf-8"
    )
    assert re.search(r"html\s*\{[^}]*font-size:\s*112\.5%", css), "root type scale missing"

    absolute = [
        size for size in re.findall(r"font-size:\s*([^;]+);", css)
        if re.search(r"\d\s*(px|pt)\b", size)
    ]
    assert not absolute, f"font sizes must be rem so the root scale reaches them: {absolute}"


# Regression: ISSUE-001 — the Triage statistics grid was `display:flex` with no
# wrap, so in the narrow Streamlit column it lives in (~120px below a 1000px
# window) three values needing ~225px overflowed the card and the third one
# ("Safety net", 1,525) rendered outside it entirely. A missing number is worse
# than a moved one. Found by /qa on 2026-07-30 at 900x800.
def test_statistics_grid_wraps_instead_of_overflowing():
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / ".streamlit" / "styles.css").read_text(
        encoding="utf-8"
    )
    block = re.search(r"\.tc-stat__grid\s*\{([^}]*)\}", css)
    assert block, ".tc-stat__grid rule missing"
    assert re.search(r"flex-wrap:\s*wrap", block.group(1)), (
        "the statistics grid must wrap — as nowrap its third value renders "
        "outside the card in a squeezed column"
    )


def test_motion_respects_prefers_reduced_motion():
    """Motion is decoration here, so it must be fully switchable off."""
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / ".streamlit" / "styles.css").read_text(
        encoding="utf-8"
    )
    assert "@media (prefers-reduced-motion: reduce)" in css
    # Anything animated needs to be reachable by that block.
    assert "animation-duration: 0.01ms !important" in css
    assert "transition-duration: 0.01ms !important" in css


def test_dark_theme_defines_its_own_hover_lift():
    """A light-theme drop shadow is invisible on a dark surface."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / ".streamlit"
    assert "--tc-lift" in (root / "styles.css").read_text(encoding="utf-8")
    assert "--tc-lift" in (root / "styles-dark.css").read_text(encoding="utf-8"), (
        "dark mode must override the hover lift or cards will not appear to raise"
    )


def test_charts_are_interactive_not_static():
    """Hover-dim and legend filtering must be in the spec, resolved by Vega."""
    import pandas as pd

    from ui.views.dashboard import _donut

    frame = pd.DataFrame({"Channel": ["Email", "Chat"], "Tickets": [3, 5]})
    spec = _donut(frame, "Channel", "Tickets").to_dict()

    params = spec.get("params", [])
    assert params, "chart carries no selection params — it is static"
    assert any(p.get("bind") == "legend" for p in params), "legend must be clickable"
    assert any("mouseover" in str(p.get("select", "")) for p in params), "hover missing"
    # The dim is what makes the selection visible at all.
    assert "opacity" in spec.get("encoding", {})


# --- "How priority is decided" explainer --------------------------------------
# The whole value of this panel is that it cannot lie about the scorer. These
# tests pin that property, not the wording: every number it shows is read from
# `src.rule_scorer` / `src.schema`, so retuning the scorer updates the panel and
# a hand-edited copy would fail here.
def test_score_bands_are_the_bands_from_score_actually_uses():
    from src.schema import SCORE_BANDS, Category

    # The cutoffs used to be inline literals in `from_score`. Anything that
    # displays them must agree with what the scorer applies.
    for category, floor in SCORE_BANDS:
        assert Category.from_score(floor) is category, f"{floor} should be {category}"
        if floor > 0:
            below = Category.from_score(floor - 1)
            assert below is not category, f"{floor - 1} should not still be {category}"


def test_safety_net_floor_is_the_high_band_floor():
    """The net assigns High, so the score it hands out must mean High."""
    from src.rule_scorer import HIGH_FLOOR
    from src.schema import SCORE_BANDS, Category

    high_floor = next(f for c, f in SCORE_BANDS if c is Category.HIGH)
    assert HIGH_FLOOR == high_floor
    assert Category.from_score(HIGH_FLOOR) is Category.HIGH


def test_explainer_reference_is_read_from_the_scorer():
    from src import rule_scorer as rs
    from ui import domain

    ref = domain.scorer_reference()
    assert ref["base"] == rs.BASE_SCORE
    assert ref["safety_net_floor"] == rs.HIGH_FLOOR

    # Bands must tile the 0-100 range with no gap and no overlap.
    bands = ref["bands"]
    assert bands[0]["ceiling"] == 100
    assert bands[-1]["floor"] == 0
    for upper, lower in zip(bands, bands[1:]):
        assert lower["ceiling"] == upper["floor"] - 1, "score bands must be contiguous"

    # Every hard trigger group must appear in the critical tier, since presence of
    # any of them is what forces escalation.
    critical = next(t for t in ref["tiers"] if t["forces_escalation"])
    names = {g["name"] for g in critical["groups"]}
    assert set(rs.HARD_TRIGGERS) <= names
    assert {g["name"] for g in ref["hard_triggers"]} == set(rs.HARD_TRIGGERS)


def test_safety_net_stats_show_the_invariant_holding():
    """No ticket the net touched may sit below High. That is the guarantee."""
    from src.schema import Category
    from ui import domain

    stats = domain.safety_net_stats()
    if not stats["total"]:
        pytest.skip("no data loaded")

    assert stats["fired"] > 0
    below = {
        name: count for name, count in stats["by_category"].items()
        if name not in (Category.CRITICAL.value, Category.HIGH.value) and count
    }
    assert not below, f"safety net left tickets below High: {below}"
    assert sum(stats["by_category"].values()) == stats["fired"]


def test_worked_example_arithmetic_adds_up():
    from ui import domain

    # A hard trigger with little other keyword mass: the case the net exists for.
    example = domain.scorer_worked_example("The billing system is down.")
    assert example["raw"] == example["base"] + sum(l["weight"] for l in example["lines"])
    assert example["safety_net_triggered"]
    assert example["lifted_by_net"], "this example should demonstrate the net lifting"
    assert example["score"] > example["raw"]
    assert example["category"] == "High"
    assert any(line["hard"] for line in example["lines"])

    # And a plain question must not trip any of it.
    calm = domain.scorer_worked_example("How do I export my report to PDF?")
    assert not calm["safety_net_triggered"]
    assert not calm["lifted_by_net"]
    assert calm["score"] == calm["raw"]


def test_safety_net_page_renders_the_explainer():
    at = AppTest.from_string(
        "from ui.views import tickets\ntickets.render_safety_net()\n", default_timeout=120
    ).run()
    assert not at.exception, at.exception
    body = _html(at)
    assert "tc-explain__net" in body, "the safety-net explanation must render"
    assert "tc-explain__row" in body, "the bands/weights rows must render"
    # The live figures, not a transcribed sentence.
    assert "guarantee about vocabulary" in body


# Every module under src/ does `from src.… import …`, so running one as a file
# path puts src/ on sys.path instead of the repo root and raises
# ModuleNotFoundError. The README's own step 1, data_prep's docstring, the
# missing-input error in batch_classify, and the app's empty-state error all told
# the user to do exactly that. Anything instructing a user how to run this
# pipeline must use `python -m src.<module>`.
def test_docs_never_tell_you_to_run_a_src_module_as_a_file():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    targets = [root / "README.md", root / "CASE_STUDY.md", root / "app.py"]
    targets += sorted((root / "src").glob("*.py"))

    offenders = [
        f"{path.name}:{n}"
        for path in targets
        if path.exists()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"python3?\s+src/\w+\.py", line)
    ]
    assert not offenders, (
        "use `python -m src.<module>` instead — running a src/ module as a file "
        f"path raises ModuleNotFoundError. Found at: {', '.join(offenders)}"
    )


# The `resolution` passthrough and the completeness flags. Both exist to replace a
# tempting-but-empty "urgent response / overdue" flag pair with something measured,
# so the tests pin the measurement rather than just the plumbing.
def test_resolution_is_carried_through_for_closed_tickets_only():
    from ui import domain

    tickets = domain.load_tickets()
    if not tickets:
        pytest.skip("no data loaded")

    with_note = [t for t in tickets if str(t.get("resolution", "")).strip()]
    closed = [t for t in tickets if t.get("status") == "Closed"]
    assert with_note, "resolution column missing from the batch — rerun batch_classify"
    # A note on a ticket that isn't closed would mean the passthrough picked up
    # the wrong column.
    assert {t["id"] for t in with_note} == {t["id"] for t in closed}


def test_resolution_state_labels_all_three_cases():
    from ui.domain import resolution_state

    assert resolution_state({"resolution": "Fixed the billing error.", "status": "Closed"}) == "Resolved"
    assert resolution_state({"resolution": "", "status": "Closed"}) == "Closed, no note recorded"
    assert resolution_state({"resolution": "", "status": "Open"}) == "Not yet resolved"
    # A batch predating the passthrough has no key at all.
    assert resolution_state({"status": "Open"}) == "Not yet resolved"


def test_completeness_flags_say_only_what_they_measure():
    from ui import domain

    frame = domain.tickets_frame()
    if frame.empty:
        pytest.skip("no data loaded")

    # Each flag must track its own mapped column, not the status column it
    # happens to correlate with.
    for flag, column in domain.COMPLETENESS_FLAGS.items():
        assert flag in frame.columns
        blank = frame[column].fillna("").astype(str).str.strip() == ""
        assert frame[flag].equals(blank), f"{flag} does not report {column}"


# This is the finding that replaced the plan's "Urgent Response" / "Overdue" flags:
# the blanks those flags would have keyed on are a pure function of `status`, so the
# flags would have renamed a column rather than added a signal. If a future dataset
# breaks the pattern, this test fails and the flags become worth building for real.
def test_blank_fields_are_fully_explained_by_status():
    from ui import domain

    completeness = domain.field_completeness()
    if not completeness:
        pytest.skip("no data loaded")

    assert {item["field"] for item in completeness} == set(domain.COMPLETENESS_FIELDS)
    for item in completeness:
        assert item["explained_by_status"], (
            f"{item['field']} has {item['mismatches']} blanks status does not explain — "
            "a real completeness flag may now carry information and should be reconsidered"
        )
        assert 0 < item["coverage"] < 1, f"{item['field']} is not partially populated"


def test_resolution_notes_are_measured_as_filler():
    """The workspace withholds the note text on the strength of these numbers."""
    from ui import domain

    facts = domain.data_integrity()
    if not facts["resolution_notes"]:
        pytest.skip("no resolution notes in this batch")

    notes = facts["resolution_notes"]
    # Every note distinct, yet almost none about support and none about the product.
    assert facts["resolution_unique"] == notes
    assert facts["resolution_domain_terms"] / notes < 0.15
    assert facts["resolution_mentions_product"] == 0


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
        # A pre-swap batch has no resolution column and no status, so the note
        # measurement and the completeness table must both report nothing found
        # rather than dividing by zero or indexing a missing column.
        assert facts["resolution_notes"] == 0
        assert facts["resolution_mentions_product"] == 0
        for item in domain.field_completeness():
            assert item["filled"] == 0
        assert domain.resolution_state(old_style[0]) == "Not yet resolved"
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


# Regression: ISSUE-012 — the queue rails rendered a bare "4433" next to the
# Dashboard's "8,469", and a filter matching exactly one ticket read "1 tickets".
# Found by /qa on 2026-07-29.
def test_counts_are_formatted_and_pluralized():
    from ui.components import count

    assert count(8469) == "8,469"
    assert count(0) == "0"
    assert count(999) == "999"
    # Percentages and pre-formatted strings must pass through untouched, or the
    # stat rails would start printing "1,00%" style nonsense.
    assert count("87%") == "87%"
    assert count("—") == "—"
    assert count(2.99) == "2.99"

    at = AppTest.from_string(TICKETS_VIEW, default_timeout=90).run()
    assert not at.exception, at.exception
    body = _html(at)
    assert "8,469 in view" in body, "chip should carry a thousands separator"
    assert ">1 tickets<" not in body, "singular count must not read '1 tickets'"


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


# Regression: ISSUE-003 — both queue pages route through `_open_detail_or` and
# share the open-tab state, so opening a ticket on Tickets and then clicking
# "Safety-net escalations" rendered that same ticket's detail under the
# escalation heading. Observed live with a ticket whose own Safety net field read
# "Not triggered": the page carrying this project's headline correctness claim
# was displaying a ticket the net never touched.
# Found by /qa on 2026-08-01.
# Report: .gstack/qa-reports/qa-report-localhost-2026-08-01.md
def test_safety_net_page_does_not_open_a_ticket_the_net_never_touched():
    script = (
        "from ui.views import tickets\n"
        "from ui import state, domain\n"
        "ts = [t for t in domain.load_tickets() if not t.get('safety_net_triggered')]\n"
        "if ts:\n"
        "    state.open_ticket(ts[0]['id'])\n"
        "tickets.render_safety_net()\n"
    )
    at = AppTest.from_string(script, default_timeout=120).run()
    assert not at.exception, at.exception

    body = _html(at)
    assert "Safety-net escalations" in body, (
        "a non-escalated ticket must fall through to this page's own queue, "
        "not hijack it"
    )
    assert "tc-explain__net" in body, "the page's own explainer must still render"


# The other half of ISSUE-003: the fix must not over-correct into "this page
# never opens anything". Opening an escalated ticket from the escalation queue is
# the intended behaviour — a ticket opens inside its view rather than as its own
# navigation entry, which is the whole premise of the tab strip.
def test_safety_net_page_still_opens_an_escalated_ticket():
    script = (
        "from ui.views import tickets\n"
        "from ui import state, domain\n"
        "ts = [t for t in domain.load_tickets() if t.get('safety_net_triggered')]\n"
        "if ts:\n"
        "    state.open_ticket(ts[0]['id'])\n"
        "tickets.render_safety_net()\n"
    )
    at = AppTest.from_string(script, default_timeout=120).run()
    assert not at.exception, at.exception

    body = _html(at)
    assert "tc-note" in body, (
        "an escalated ticket must still open inline on the escalation page"
    )


# Regression: ISSUE-004 — when the rail collapses, Streamlit floats a control
# carrying the logo and the expand arrow at the top-left of the workspace. It is
# `position: fixed`, so nothing below it moves out of the way. Measured at
# 1440x900: the control sat at y 22-67 while the open-ticket tab strip sat at
# y 40, and the logo covered the left 17x22px of the first tab including its
# priority dot. Found by /qa on 2026-08-01.
# Report: .gstack/qa-reports/qa-report-localhost-2026-08-01.md
def test_collapsed_rail_reserves_room_for_the_floating_logo():
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / ".streamlit" / "styles.css").read_text(
        encoding="utf-8"
    )
    rule = re.search(
        r"\.stApp:has\(\[data-testid=\"stSidebarCollapsedControl\"\]\)\s*"
        r"\[data-testid=\"stMainBlockContainer\"\]\s*\{([^}]*)\}",
        css,
    )
    assert rule, (
        "the collapsed-rail padding rule is missing — without it the floating "
        "logo overlaps the open-ticket tab strip"
    )
    pad = re.search(r"padding-top:\s*([\d.]+)rem", rule.group(1))
    assert pad, "the rule must set padding-top"
    # The control's foot measured 67px; at a 112.5% root (18px) the tab strip
    # clears it from 3rem upward. Below that the overlap returns silently.
    assert float(pad.group(1)) >= 3.0, (
        f"padding-top {pad.group(1)}rem is too small to clear the 67px control"
    )


# Regression: ISSUE-001 — a popover's body is portaled out of the component tree
# when it opens, landing outside both stMain and stSidebar. The dark sheet's
# button rule is scoped to stMain, so the account menu kept the light theme's
# white button fill while its labels resolved through --tc-text (near-white in
# dark mode). Measured 1.22:1 against a 4.5:1 floor — the labels were invisible.
# Found by /qa on 2026-08-01.
# Report: .gstack/qa-reports/qa-report-localhost-2026-08-01.md
def test_dark_theme_reaches_inside_portaled_popovers():
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / ".streamlit" / "styles-dark.css").read_text(
        encoding="utf-8"
    )
    rule = re.search(
        r"\[data-testid=\"stPopoverBody\"\]\s*\[data-testid=\"stButton\"\]\s*button\s*\{([^}]*)\}",
        css,
    )
    assert rule, (
        "dark mode must theme buttons INSIDE the popover body, not just the body "
        "itself — the stMain-scoped rule cannot reach a portaled popover"
    )
    body = rule.group(1)
    assert "var(--tc-surface)" in body, "the button fill must follow the theme token"
    assert "var(--tc-text)" in body, "the button label must follow the theme token"


# Regression: ISSUE-006 — the statistics rail is shared by Tickets and Safety-net
# escalations. On the escalation page every ticket in view triggered the net by
# definition, so "Safety net 1,525" simply restated the "1,525 tickets" header a
# few hundred pixels to its left. On Tickets the same figure is real information:
# how much of the queue the scorer overrode. Found by /qa on 2026-08-01.
# Report: .gstack/qa-reports/qa-report-localhost-2026-08-01.md
def test_safety_net_rail_drops_a_count_that_is_always_the_whole_page():
    from ui.views import tickets as tickets_view

    escalated = [
        {"id": "T1", "category": "Critical", "score": 70, "safety_net_triggered": True},
        {"id": "T2", "category": "High", "score": 70, "safety_net_triggered": True},
    ]
    mixed = escalated + [
        {"id": "T3", "category": "Low", "score": 30, "safety_net_triggered": False},
    ]

    def rail_labels(batch):
        script = (
            "from ui.views import tickets\n"
            f"tickets._statistics_rail({batch!r})\n"
        )
        at = AppTest.from_string(script, default_timeout=90).run()
        assert not at.exception, at.exception
        return _html(at)

    all_escalated = rail_labels(escalated)
    assert "Safety net" not in all_escalated, (
        "on a page where every ticket triggered the net, the count restates the "
        "header and must not be shown"
    )
    assert "Critical" in all_escalated, "the informative counts must survive"

    partly = rail_labels(mixed)
    assert "Safety net" in partly, (
        "on a mixed queue the safety-net count is real information about how "
        "much of it the scorer overrode"
    )


# Regression: the keyboard contract. Before this, styles.css had exactly ONE
# focus rule, scoped to [data-testid="stMainBlockContainer"] ... button, which
# measured (in the browser) as a visible focus ring on 1 of 6 distinct control
# kinds. Nav links, the profile popover, and the slider had none. Same scoping
# mistake as ISSUE-001: a rule written against one DOM path instead of against
# control classes. Found by /qa on 2026-08-01.
# Report: .gstack/qa-reports/qa-report-localhost-2026-08-01.md
def _css():
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / ".streamlit" / "styles.css").read_text(
        encoding="utf-8"
    )


def _ratio(hex_a: str, hex_b: str) -> float:
    def lum(h):
        h = h.lstrip("#")
        out = []
        for i in (0, 2, 4):
            v = int(h[i:i + 2], 16) / 255
            out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]

    a, b = lum(hex_a), lum(hex_b)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_focus_ring_reaches_every_control_class():
    css = _css()
    # Each of these was measured as having NO focus style before the contract.
    for needed in (
        "stSidebarNavLink",      # the 7 rail links
        "stPopover",             # the account menu trigger
        "stSlider",              # the Home-list size control
        "stSelectbox",
        "stMultiSelect",
        "stTextInput",
        "stTextArea",
        "stExpander",
    ):
        assert re.search(rf"{needed}[^{{]*:focus(-visible|-within)", css), (
            f"{needed} has no focus rule — a keyboard user cannot see it"
        )


def test_focus_ring_clears_the_wcag_floor_on_both_surfaces():
    """WCAG 2.2 SC 1.4.11: focus indicators need 3:1 against their background.

    The rail is why this exists. --tc-primary (#1F73B7) on #03363D measures
    2.62:1, so a single ring token cannot serve both surfaces.
    """
    css = _css()
    rail_ring = re.search(r"--tc-focus-ring-rail:\s*(#[0-9A-Fa-f]{6})", css)
    assert rail_ring, "the rail needs its own focus-ring token"

    rail_bg = re.search(r"--tc-rail:\s*(#[0-9A-Fa-f]{6})", css)
    assert rail_bg, "--tc-rail missing"

    ratio = _ratio(rail_ring.group(1), rail_bg.group(1))
    assert ratio >= 3.0, (
        f"focus ring {rail_ring.group(1)} on rail {rail_bg.group(1)} is "
        f"{ratio:.2f}:1, below the 3:1 floor"
    )
    # The old single-token value is the exact thing this guards against.
    assert _ratio("#1F73B7", rail_bg.group(1)) < 3.0, (
        "sanity check: --tc-primary was supposed to be the failing value"
    )


def test_notifications_panel_has_no_dead_toggles():
    """Three toggles shipped disabled=True forever, explaining their own uselessness.

    A control that cannot be operated has not earned its pixels.
    """
    at = AppTest.from_string(
        "from ui.views import settings\nsettings.render()\n", default_timeout=120
    ).run()
    assert not at.exception, at.exception
    labels = [t.label for t in at.get("toggle")]
    for dead in ("Email me when a Critical ticket arrives",
                 "Email me when a ticket breaches SLA",
                 "Daily queue digest"):
        assert dead not in labels, f"{dead!r} is a control that does nothing"
    # Dark mode is a real preference and must survive the cut.
    assert "Dark mode" in labels, "the one working toggle must remain"


# Regression: ISSUE-002 — the ISSUE-009 fix kept `value=`/`index=` on the Settings
# widgets, recomputed from the durable key. That looked harmless and re-mounted
# each widget on every rerun, which DROPPED KEYBOARD FOCUS. Measured in a browser:
# starting at 3 and pressing Right five times to reach 8 produced 4, 4, 4, 4, 4 --
# the first press landed, then focus fell to <body> and the rest went nowhere.
# The user reported it as "the Tickets bar glitches from 3 to 8".
# Found by /qa on 2026-08-01.
# Report: .gstack/qa-reports/qa-report-localhost-2026-08-01.md
def test_settings_widgets_are_never_handed_a_value():
    """A widget with both a key and a recomputed value re-mounts and loses focus."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "ui" / "views" / "settings.py"
    ).read_text(encoding="utf-8")

    slider = re.search(r"st\.slider\((.*?)\n        \)", src, re.S)
    assert slider, "the Home-list slider is missing"
    # `value=` as its own keyword, not the tail of min_value=/max_value=, which
    # are the range and are required.
    assert not re.search(r"(?<![_a-zA-Z])value=", slider.group(1)), (
        "the slider must not be given value= — that prop changes every rerun, "
        "re-mounts the widget, and drops keyboard focus (ISSUE-002)"
    )

    selectbox = re.search(r"st\.selectbox\((.*?)\n        \)", src, re.S)
    assert selectbox, "the default-sort selectbox is missing"
    assert not re.search(r"(?<![_a-zA-Z])index=", selectbox.group(1)), (
        "the selectbox must not be given index= — same re-mount problem as the "
        "slider, and it is the twin defect that was never reported"
    )


def test_bind_seeds_only_when_the_widget_key_is_absent():
    """Present means the widget is mid-interaction and owns the truth."""
    script = (
        "import streamlit as st\n"
        "from ui import prefs\n"
        "st.session_state[prefs.ATTENTION_LIMIT] = 11\n"
        "prefs.bind(prefs.W_ATTENTION_LIMIT, prefs.ATTENTION_LIMIT, 6)\n"
        "first = st.session_state[prefs.W_ATTENTION_LIMIT]\n"
        "# a later rerun must NOT clobber what the user is currently dragging\n"
        "st.session_state[prefs.W_ATTENTION_LIMIT] = 15\n"
        "prefs.bind(prefs.W_ATTENTION_LIMIT, prefs.ATTENTION_LIMIT, 6)\n"
        "st.write(f'seeded={first} kept={st.session_state[prefs.W_ATTENTION_LIMIT]}')\n"
    )
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, at.exception
    body = "\n".join(str(m.value) for m in at.markdown)
    assert "seeded=11 kept=15" in body, body


def test_bind_coerces_a_stored_value_that_is_out_of_range():
    """A saved 20 against a slider that stops at 15 would make Streamlit raise."""
    from ui import prefs

    assert prefs.clamp_attention_limit(20) == prefs.ATTENTION_LIMIT_MAX
    assert prefs.clamp_attention_limit(1) == prefs.ATTENTION_LIMIT_MIN
    assert prefs.clamp_attention_limit("8") == 8


def test_attention_limit_survives_a_junk_stored_value():
    """Shadow path: anything non-numeric must fall back, never raise."""
    script = (
        "import streamlit as st\n"
        "from ui import prefs\n"
        "st.session_state[prefs.ATTENTION_LIMIT] = 'banana'\n"
        "st.write(f'limit={prefs.attention_limit()}')\n"
    )
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, at.exception
    body = "\n".join(str(m.value) for m in at.markdown)
    assert f"limit={6}" in body, body


def test_prefs_is_the_base_layer_and_imports_nothing_from_ui():
    """theme.py and state.py both depend on prefs, so it must sit below them."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "ui" / "prefs.py"
    ).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+ui\b", src, re.M), (
        "ui/prefs.py must import nothing from ui/ — it is the base of the graph, "
        "and a cycle here is what the local-import dodges elsewhere existed for"
    )


# Regression: ISSUE-005 — the dataset ships its label vocabulary in sentence case,
# so the console rendered "Refund request", "Billing inquiry", "Cancellation
# request", "Product inquiry", "Technical issue" and "Social media" next to its
# own title-case chrome. Reported as "capitalize the R in Refund Request"; it is
# five ticket types plus a channel plus sixteen subjects, not one string.
# Found by /qa on 2026-08-01.
# Report: .gstack/qa-reports/qa-report-localhost-2026-08-01.md
def test_humanize_capitalises_dataset_labels():
    from ui.components import humanize

    assert humanize("Refund request") == "Refund Request"
    assert humanize("Billing inquiry") == "Billing Inquiry"
    assert humanize("Cancellation request") == "Cancellation Request"
    assert humanize("Product inquiry") == "Product Inquiry"
    assert humanize("Technical issue") == "Technical Issue"
    assert humanize("Social media") == "Social Media"


def test_humanize_does_not_wreck_product_names():
    """str.title() is the obvious tool and it is wrong: the same tag list carries
    product names, so it would render "Asus ROG" as "Asus Rog"."""
    from ui.components import humanize

    for untouched in ("Asus ROG", "HP Pavilion", "GoPro Hero", "iPhone",
                      "Pending Customer Response", "LG OLED"):
        assert humanize(untouched) == untouched, (
            f"{untouched!r} already carries capitals and must survive unchanged"
        )
    # The naive implementation this guards against:
    assert "Asus ROG".title() != humanize("Asus ROG")


def test_humanize_handles_the_empty_and_missing_cases():
    from ui.components import humanize

    assert humanize(None) == ""
    assert humanize("") == ""
    assert humanize("—") == "—"


def test_no_raw_lowercase_dataset_label_reaches_the_queue():
    """End to end: render the real queue and assert the tags are cased."""
    at = AppTest.from_string(TICKETS_VIEW, default_timeout=120).run()
    assert not at.exception, at.exception
    body = _html(at)
    for raw in ("Refund request", "Billing inquiry", "Product inquiry",
                "Technical issue", "Cancellation request", "Social media"):
        assert raw not in body, f"{raw!r} reached the DOM uncased"
