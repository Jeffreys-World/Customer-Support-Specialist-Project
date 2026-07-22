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
