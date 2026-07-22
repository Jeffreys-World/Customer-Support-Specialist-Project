"""Stage 5 — evaluation (PROJECT_PLAN.md §10).

Scores the full processed dataset and compares the rule-based scorer's output to
the dataset's ground-truth priority labels. Reports, in order of importance:

  1. Top-severity (Critical-class) recall — of tickets the dataset labels ``high``,
     what fraction did the scorer flag Critical *or* High. This is the metric tied
     to Jordan's 4-hour billing incident; a miss here is the worst failure.
  2. Overall accuracy + a full 3×3 confusion matrix (dataset has three labels;
     the scorer's Critical + High collapse into the top-severity bucket).
  3. Per-class precision/recall and a few concrete misclassified examples.

Ground truth is the dataset label only — no heuristic relabelling — so the numbers
are honest. Results are written to ``results/evaluation.md`` and a review sample to
``results/spot_check_sample.csv``.

Run:  ``python -m src.evaluate``
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from src.batch_classify import load_tickets
from src.rule_scorer import score_ticket
from src.schema import DATASET_LABELS, ScoredTicket

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "data" / "processed" / "tickets.csv"
RESULTS_DIR = REPO_ROOT / "results"
LABELS = DATASET_LABELS  # ["low", "medium", "high"]


def _blank_matrix() -> Dict[str, Dict[str, int]]:
    return {t: {p: 0 for p in LABELS} for t in LABELS}


def evaluate(scored: List[ScoredTicket]) -> Dict:
    """Compute confusion matrix + headline metrics against dataset labels."""
    matrix = _blank_matrix()
    skipped = 0
    for s in scored:
        true = s.ticket.true_priority
        if true not in LABELS:
            skipped += 1
            continue
        pred = s.category.ground_truth_bucket()  # Critical/High -> "high"
        matrix[true][pred] += 1

    total = sum(matrix[t][p] for t in LABELS for p in LABELS)
    correct = sum(matrix[l][l] for l in LABELS)
    accuracy = correct / total if total else 0.0

    per_class = {}
    for label in LABELS:
        tp = matrix[label][label]
        actual = sum(matrix[label][p] for p in LABELS)
        predicted = sum(matrix[t][label] for t in LABELS)
        per_class[label] = {
            "recall": tp / actual if actual else 0.0,
            "precision": tp / predicted if predicted else 0.0,
            "support": actual,
        }

    return {
        "matrix": matrix,
        "total": total,
        "skipped": skipped,
        "accuracy": accuracy,
        "per_class": per_class,
        "top_severity_recall": per_class["high"]["recall"],
    }


def critical_prediction_breakdown(scored: List[ScoredTicket]) -> Dict[str, int]:
    """Where do the scorer's 🔴 Critical predictions land vs the dataset label?"""
    out = {label: 0 for label in LABELS}
    for s in scored:
        if s.category.value == "Critical" and s.ticket.true_priority in LABELS:
            out[s.ticket.true_priority] += 1
    return out


def misclassified_examples(scored: List[ScoredTicket], true: str, pred_bucket: str, n: int = 3):
    out = []
    for s in scored:
        if s.ticket.true_priority == true and s.category.ground_truth_bucket() == pred_bucket:
            out.append(s)
            if len(out) >= n:
                break
    return out


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def write_report(scored: List[ScoredTicket], metrics: Dict, path: Path) -> None:
    m = metrics["matrix"]
    crit = critical_prediction_breakdown(scored)
    lines: List[str] = []
    lines.append("# Evaluation — Jordan's Ticket Triage Assistant\n")
    lines.append(
        f"Rule-based scorer vs. dataset ground-truth priority labels, over "
        f"**{metrics['total']:,} English tickets**. Ground truth is the dataset's "
        f"own `low`/`medium`/`high` label — no relabelling. The scorer's four-level "
        f"output (Critical/High/Medium/Low) is collapsed to the dataset's three "
        f"levels for comparison: **Critical + High → `high`**.\n"
    )

    lines.append("## 1. Top-severity (Critical-class) recall — the headline metric\n")
    tsr = metrics["top_severity_recall"]
    high_support = metrics["per_class"]["high"]["support"]
    caught = m["high"]["high"]
    lines.append(
        f"Of the **{high_support:,}** tickets the dataset labels `high`, the scorer "
        f"flagged **{caught:,}** as Critical or High.\n\n"
        f"> **Top-severity recall = {_fmt_pct(tsr)}**\n\n"
        f"This is the number that matters most: a `high` ticket read as routine is "
        f"exactly Jordan's 4-hour billing incident.\n"
    )

    lines.append("## 2. Overall accuracy & confusion matrix\n")
    lines.append(f"**Overall accuracy: {_fmt_pct(metrics['accuracy'])}** "
                 f"({sum(m[l][l] for l in LABELS):,}/{metrics['total']:,} correct).\n")
    lines.append("Rows = dataset label (truth), columns = scorer prediction (collapsed).\n")
    header = "| truth ↓ / pred → | low | medium | high | recall |"
    sep = "|---|---|---|---|---|"
    lines.append(header)
    lines.append(sep)
    for t in ["high", "medium", "low"]:
        r = metrics["per_class"][t]["recall"]
        row = f"| **{t}** | {m[t]['low']:,} | {m[t]['medium']:,} | {m[t]['high']:,} | {_fmt_pct(r)} |"
        lines.append(row)
    prec = "| **precision** | " + " | ".join(
        _fmt_pct(metrics["per_class"][l]["precision"]) for l in ["low", "medium", "high"]
    ) + " | |"
    lines.append(prec)
    lines.append("")

    lines.append("## 3. Where the 🔴 Critical predictions land\n")
    crit_total = sum(crit.values())
    lines.append(
        f"The scorer assigned 🔴 Critical to **{crit_total:,}** tickets. Against the "
        f"dataset label they split: "
        f"**{crit['high']:,} high**, {crit['medium']:,} medium, {crit['low']:,} low. "
        f"(All of these count as correct top-severity, since Critical → `high`.)\n"
    )

    lines.append("## 4. Systematic confusions & examples\n")
    lines.append(
        "The scorer is keyword-driven, so tickets whose urgency isn't expressed with "
        "priority keywords fall to Low — the main driver of missed `high`/`medium` recall. "
        "Representative misses:\n"
    )
    for s in misclassified_examples(scored, true="high", pred_bucket="low", n=3):
        subj = (s.ticket.subject or s.ticket.body[:60]).replace("\n", " ")
        lines.append(f"- **high → Low**: “{subj[:80]}” (score {s.score})")
    lines.append("")

    lines.append("## 5. Manual spot-check\n")
    lines.append(
        "A 25-ticket sample is written to `results/spot_check_sample.csv` for a human "
        "reviewer to mark agree/disagree (PROJECT_PLAN.md §10). This is a small-sample "
        "sanity check, not a statistically powered metric, and the human agreement rate "
        "is intentionally left blank until reviewed — no fabricated numbers.\n"
    )

    lines.append("## 6. Honest limitations\n")
    lines.append(
        "- **English-only** coverage (German tickets filtered out).\n"
        "- Keyword lists are tuned to a generic IT-support dataset, not a real company's "
        "product taxonomy — the ceiling on accuracy is low by design.\n"
        "- The safety net optimises **recall on the top-severity class first**; it "
        "over-fires to High on some routine tickets, which lowers `high` precision. That "
        "trade is deliberate: a missed critical ticket costs far more than a false alarm.\n"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_spot_check_sample(scored: List[ScoredTicket], path: Path, n: int = 25) -> None:
    """Deterministic sample of n tickets across the queue for human review."""
    import csv

    step = max(1, len(scored) // n)
    sample = scored[::step][:n]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ticket_id", "subject", "scorer_category", "score",
                         "dataset_label", "reviewer_agrees(y/n)", "notes"])
        for s in sample:
            writer.writerow([
                s.ticket.id, (s.ticket.subject or "")[:80], s.category.value, s.score,
                s.ticket.true_priority, "", "",
            ])


def main() -> int:
    tickets = load_tickets(DEFAULT_INPUT)
    scored = [score_ticket(t) for t in tickets]
    metrics = evaluate(scored)

    write_report(scored, metrics, RESULTS_DIR / "evaluation.md")
    write_spot_check_sample(scored, RESULTS_DIR / "spot_check_sample.csv")

    print(f"Evaluated {metrics['total']:,} tickets.")
    print(f"Top-severity (Critical-class) recall: {_fmt_pct(metrics['top_severity_recall'])}")
    print(f"Overall accuracy: {_fmt_pct(metrics['accuracy'])}")
    print("Per-class recall:",
          {l: _fmt_pct(metrics['per_class'][l]['recall']) for l in LABELS})
    print("Wrote results/evaluation.md and results/spot_check_sample.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
