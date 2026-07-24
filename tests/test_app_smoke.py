"""Smoke test for the Streamlit UI.

Runs the full app script in Streamlit's simulated harness (no browser) and
asserts it renders without raising — enough to catch layout/API breakage in CI
without a live batch or API key.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402


def test_app_runs_without_exception():
    at = AppTest.from_file("app.py", default_timeout=30).run()
    assert not at.exception, at.exception
    # Title always renders; if data is present, the four priority metrics show too.
    assert any("Triage" in md.value for md in at.title)


def test_sla_and_age_helpers_are_deterministic():
    from app import simulated_age_hours, sla_state

    assert simulated_age_hours("T00001") == simulated_age_hours("T00001")
    assert 0 <= simulated_age_hours("T00042") <= 48
    assert "breached" in sla_state("Critical", age_hours=10)  # 1h target, 10h old


# Regression: ISSUE-001 — "Tickets in queue" metric showed the full dataset size
# (len(tickets)) instead of the filtered count, so it read 800 even when a search
# or priority filter narrowed the queue to a handful.
# Found by /qa on 2026-07-24.
# Report: .gstack/qa-reports/qa-report-localhost-8501-2026-07-24.md
def test_tickets_in_queue_metric_tracks_active_filter():
    at = AppTest.from_file("app.py", default_timeout=30).run()
    assert not at.exception, at.exception

    labelled = {m.label: m.value for m in at.metric}
    if "Tickets in queue" not in labelled:
        pytest.skip("no data loaded — metric not rendered")
    baseline = int(labelled["Tickets in queue"])

    # Apply a search that narrows the queue to a subset.
    at.text_input[0].set_value("breach").run()
    assert not at.exception, at.exception

    metrics = {m.label: m.value for m in at.metric}
    queue_size = int(metrics["Tickets in queue"])
    kpi_sum = sum(int(v) for label, v in metrics.items() if label != "Tickets in queue")

    # Every filtered ticket falls in exactly one category, so the queue-size metric
    # must equal the sum of the category KPIs. The bug made it read the full dataset
    # while the categories summed to the filtered count.
    assert queue_size == kpi_sum
    # And the filter must actually have reduced the set (else the test is a no-op
    # that would pass even with the bug present).
    assert queue_size < baseline
