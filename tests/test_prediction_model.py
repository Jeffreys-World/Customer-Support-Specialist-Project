"""Tests for the priority-prediction ceiling experiment.

Two things are worth pinning here, and neither is "the model works".

First, **isolation**. IMPLEMENTATION_PLAN.md Phase 2 required the model be built
standalone: not importing the console, not imported by it. That is a structural
property a future refactor could break silently, so it is asserted rather than
trusted.

Second, **the negative result itself**. The whole justification for not shipping a
``Predicted_Priority`` column is that no feature set beats guessing. If a future
dataset swap makes the label learnable, these tests fail — which is the signal that
the decision should be revisited, not a bug.

The experiment runs against the committed 799-ticket sample rather than the full
batch, so the suite stays fast and works on a fresh clone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("sklearn")

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "data" / "processed" / "classified_tickets.sample.json"


@pytest.fixture(scope="module")
def summary():
    from prediction_model import run

    if not SAMPLE.exists():
        pytest.skip("committed demo sample missing")
    return run(SAMPLE)


# --- Isolation (Phase 2's explicit requirement) --------------------------------

def test_experiment_does_not_import_the_console():
    source = (REPO_ROOT / "prediction_model.py").read_text(encoding="utf-8")
    imports = re.findall(r"^\s*(?:from|import)\s+([\w.]+)", source, re.MULTILINE)
    console = [name for name in imports if name == "ui" or name.startswith("ui.")]
    assert not console, f"prediction_model must not import the console: {console}"


def test_the_console_does_not_import_the_experiment():
    """The dashboard must not gain a dependency on an experiment, or a missing
    scikit-learn would take the whole app down."""
    console_files = [
        *(REPO_ROOT / "ui").rglob("*.py"),
        *(REPO_ROOT / "src").glob("*.py"),
        REPO_ROOT / "app.py",
    ]
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in console_files
        if re.search(r"^\s*(?:from|import)\s+prediction_model",
                     path.read_text(encoding="utf-8"), re.MULTILINE)
    ]
    assert not offenders, f"the console imports the experiment: {offenders}"


def test_no_predicted_priority_column_reached_the_batch():
    """Phase 2 proposed merging one in. It was deliberately not done."""
    from ui import domain

    tickets = domain.load_tickets()
    if not tickets:
        pytest.skip("no data loaded")
    assert "Predicted_Priority" not in tickets[0]
    assert "predicted_priority" not in tickets[0]


# --- The negative result ------------------------------------------------------

def test_no_feature_set_beats_the_majority_baseline(summary):
    from prediction_model import verdict

    call = verdict(summary)
    assert not call["beats_baseline"], (
        f"{call['best']['features']} now beats the majority-class baseline by "
        f"{call['margin_vs_majority'] * 100:.1f} pts (> 2 SE). The label may have become "
        "learnable — revisit the decision not to ship a predicted-priority column."
    )


def test_every_feature_set_was_actually_tried(summary):
    assert {r["features"] for r in summary["results"]} == {"plan-features", "tabular", "text"}
    # The text model is the strongest attempt; if it were not fitting at all its
    # train accuracy would sit at the baseline too, and the ceiling claim would be
    # about a broken pipeline rather than about the data.
    text = next(r for r in summary["results"] if r["features"] == "text")
    assert text["train_accuracy"] > 0.4, "text model did not fit — ceiling claim is unsupported"


def test_train_accuracy_far_exceeds_holdout(summary):
    """The gap is the point: the plan's snippet would have reported the left number."""
    for result in summary["results"]:
        assert result["train_accuracy"] > result["holdout_accuracy"] + 0.2, (
            f"{result['features']} shows no memorisation gap — unexpected, since these "
            "models fit noise by construction"
        )


def test_verdict_would_recognise_a_real_edge():
    """Guard against a vacuous guard: verdict() must be able to say yes."""
    from prediction_model import verdict

    strong = {
        "baselines": {"chance": 0.25, "majority_class": 0.26},
        "results": [{"features": "hypothetical", "holdout_accuracy": 0.85, "test_n": 1694}],
    }
    assert verdict(strong)["beats_baseline"]


def test_results_are_reproducible(summary):
    from prediction_model import run

    again = run(SAMPLE)
    first = {r["features"]: r["holdout_accuracy"] for r in summary["results"]}
    second = {r["features"]: r["holdout_accuracy"] for r in again["results"]}
    assert first == second, "seeded run drifted between invocations"


def test_report_renders_from_the_measured_numbers(summary):
    from prediction_model import format_report

    report = format_report(summary)
    assert report.startswith("# Priority prediction")
    # Headline numbers must come from the summary, not be hardcoded prose.
    best = max(summary["results"], key=lambda r: r["holdout_accuracy"])
    assert f"{best['holdout_accuracy'] * 100:.1f}%" in report
    assert "Predicted_Priority" in report, "the report must say what was not shipped"
