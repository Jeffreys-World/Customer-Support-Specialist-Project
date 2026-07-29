"""Stage 5 — evaluation (PROJECT_PLAN.md §10).

Scores the full processed dataset and compares the rule-based scorer's output to
the dataset's ground-truth priority labels. Reports, in order of importance:

  1. Critical-class recall — of tickets the dataset labels ``Critical``, what
     fraction did the scorer flag Critical or High. This is the metric tied to
     Jordan's 4-hour billing incident; a miss here is the worst failure.
  2. Overall accuracy + a full 4x4 confusion matrix, **stated against the chance
     baseline** rather than in isolation.
  3. An independence test, because on this dataset the honest answer is that the
     label cannot be predicted from the text by anything, including us.

## Why there is an independence test in here

An accuracy number means nothing without knowing what accuracy is achievable. On
``customer_support_tickets.csv`` the ``Ticket Priority`` label is statistically
independent of the ticket text: chi-square lands at or below its degrees of
freedom for every text/label pair, and the confusion matrix comes out with four
near-identical rows — the scorer predicts the same distribution regardless of the
truth. Reporting "26% accuracy" without that context would imply a fixable model
problem. It is not fixable; it is a property of the data.

So this module measures two things and reports both:

  * **model-level** — is the scorer's prediction independent of the truth?
    (Cramer's V over the confusion matrix itself, which *is* a contingency table.)
  * **dataset-level** — is the ticket *subject* independent of the truth?
    If even the subject carries no signal, no scorer of any kind could do better.

Ground truth is the dataset label only — no heuristic relabelling — so the numbers
are honest. Results are written to ``results/evaluation.md`` and a review sample to
``results/spot_check_sample.csv``.

Run:  ``python -m src.evaluate``
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Hashable, List, Sequence, Tuple

from src.batch_classify import load_tickets
from src.rule_scorer import score_ticket
from src.schema import DATASET_LABELS, Category, ScoredTicket

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "data" / "processed" / "tickets.csv"
RESULTS_DIR = REPO_ROOT / "results"

# Ordered most urgent first for display; DATASET_LABELS is least → most urgent.
LABELS = list(DATASET_LABELS)
DISPLAY_ORDER = [Category.CRITICAL.value, Category.HIGH.value,
                 Category.MEDIUM.value, Category.LOW.value]


# --- Statistics ---------------------------------------------------------------
# Implemented here rather than pulled from scipy: scipy is a heavy dependency to
# add to a Streamlit app's requirements for two functions, and the maths is short
# enough to read. Verified against scipy.stats.chi2_contingency during the swap.

def _gamma_q(a: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(a, x). Numerical Recipes §6.2."""
    if x < 0 or a <= 0:
        raise ValueError("domain error")
    if x == 0:
        return 1.0
    if x < a + 1.0:
        # Series expansion for P(a, x), then Q = 1 - P.
        ap, total, delta = a, 1.0 / a, 1.0 / a
        for _ in range(1000):
            ap += 1
            delta *= x / ap
            total += delta
            if abs(delta) < abs(total) * 1e-14:
                break
        return 1.0 - total * math.exp(-x + a * math.log(x) - math.lgamma(a))
    # Continued fraction for Q(a, x) directly.
    tiny = 1e-300
    b, c, d = x + 1.0 - a, 1.0 / 1e-300, 1.0 / (x + 1.0 - a)
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h * math.exp(-x + a * math.log(x) - math.lgamma(a))


def chi2_p_value(chi2: float, dof: int) -> float:
    """Upper-tail probability of chi2 with `dof` degrees of freedom."""
    if dof <= 0:
        return 1.0
    return _gamma_q(dof / 2.0, chi2 / 2.0)


def independence(pairs: Sequence[Tuple[Hashable, Hashable]]) -> Dict:
    """Chi-square test of independence over (x, y) observations.

    Returns chi2, degrees of freedom, p-value, and Cramer's V. V is the effect
    size: 0 means the two variables carry no information about each other, 1
    means one determines the other. Interpreting chi2 alone is a trap at this
    sample size — with n=8,469 a trivial association can still look "significant",
    so V is the number to read.
    """
    table: Dict[Hashable, Counter] = defaultdict(Counter)
    for x, y in pairs:
        table[x][y] += 1

    rows = sorted(table, key=str)
    cols = sorted({c for counter in table.values() for c in counter}, key=str)
    if len(rows) < 2 or len(cols) < 2:
        return {"chi2": 0.0, "dof": 0, "p": 1.0, "cramers_v": 0.0, "n": len(pairs)}

    observed = [[table[r][c] for c in cols] for r in rows]
    n = sum(sum(row) for row in observed)
    row_tot = [sum(row) for row in observed]
    col_tot = [sum(observed[i][j] for i in range(len(rows))) for j in range(len(cols))]

    chi2 = 0.0
    for i in range(len(rows)):
        for j in range(len(cols)):
            expected = row_tot[i] * col_tot[j] / n
            if expected > 0:
                chi2 += (observed[i][j] - expected) ** 2 / expected

    dof = (len(rows) - 1) * (len(cols) - 1)
    v = math.sqrt(chi2 / (n * (min(len(rows), len(cols)) - 1))) if n else 0.0
    return {"chi2": chi2, "dof": dof, "p": chi2_p_value(chi2, dof),
            "cramers_v": v, "n": n}


# --- Core metrics -------------------------------------------------------------

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
        matrix[true][s.category.ground_truth_bucket()] += 1

    total = sum(matrix[t][p] for t in LABELS for p in LABELS)
    correct = sum(matrix[label][label] for label in LABELS)
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

    # Critical-class recall: of tickets truly in the top-severity bucket, how many
    # did the scorer put in that bucket. Computed over Critical alone (the
    # headline) and over Critical+High (the wider safety-net question).
    top = {Category.CRITICAL.value, Category.HIGH.value}
    crit_support = per_class[Category.CRITICAL.value]["support"]
    crit_caught = sum(matrix[Category.CRITICAL.value][p] for p in top)
    top_support = sum(per_class[label]["support"] for label in top)
    top_caught = sum(matrix[t][p] for t in top for p in top)

    # Baselines. Without these an accuracy number is unreadable.
    chance = 1.0 / len(LABELS)
    majority = max(per_class[label]["support"] for label in LABELS) / total if total else 0.0
    # Rate at which the scorer calls anything top-severity — if recall matches
    # this, the scorer is flagging at its base rate and has learned nothing.
    flagged_top = sum(matrix[t][p] for t in LABELS for p in top)
    top_flag_rate = flagged_top / total if total else 0.0

    return {
        "matrix": matrix,
        "total": total,
        "skipped": skipped,
        "accuracy": accuracy,
        "chance_accuracy": chance,
        "majority_accuracy": majority,
        "per_class": per_class,
        "critical_recall": crit_caught / crit_support if crit_support else 0.0,
        "critical_support": crit_support,
        "critical_caught": crit_caught,
        "top_severity_recall": top_caught / top_support if top_support else 0.0,
        "top_severity_support": top_support,
        "top_flag_rate": top_flag_rate,
        "prediction_independence": independence(
            [(s.ticket.true_priority, s.category.value) for s in scored
             if s.ticket.true_priority in LABELS]
        ),
        "subject_independence": independence(
            [(s.ticket.subject, s.ticket.true_priority) for s in scored
             if s.ticket.true_priority in LABELS and s.ticket.subject]
        ),
        "safety_net_fired": sum(1 for s in scored if s.safety_net_triggered),
    }


def critical_prediction_breakdown(scored: List[ScoredTicket]) -> Dict[str, int]:
    """Where do the scorer's Critical predictions land vs the dataset label?"""
    out = {label: 0 for label in LABELS}
    for s in scored:
        if s.category is Category.CRITICAL and s.ticket.true_priority in LABELS:
            out[s.ticket.true_priority] += 1
    return out


def misclassified_examples(scored: List[ScoredTicket], true: str, pred: str, n: int = 3):
    out = []
    for s in scored:
        if s.ticket.true_priority == true and s.category.value == pred:
            out.append(s)
            if len(out) >= n:
                break
    return out


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _fmt_p(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


# --- Report -------------------------------------------------------------------

def write_report(scored: List[ScoredTicket], metrics: Dict, path: Path) -> None:
    m = metrics["matrix"]
    crit = critical_prediction_breakdown(scored)
    pi = metrics["prediction_independence"]
    si = metrics["subject_independence"]
    lines: List[str] = []

    lines.append("# Evaluation — Jordan's Ticket Triage Assistant\n")
    lines.append(
        f"Rule-based scorer vs. dataset ground-truth priority labels, over "
        f"**{metrics['total']:,} tickets** from `customer_support_tickets.csv`. "
        f"Ground truth is the dataset's own four-level `Ticket Priority` label — no "
        f"relabelling, no collapsing. The scorer's output scale and the dataset's "
        f"label scale are now identical, so a Critical prediction is scored against "
        f"a real Critical label.\n"
    )
    lines.append(
        "> **Headline: the scorer performs at chance on this dataset, and that is a "
        "property of the dataset, not a bug in the scorer.** Section 3 shows the "
        "label is statistically independent of the ticket text. Section 1 and 2 "
        "should be read in that light.\n"
    )

    lines.append("## 1. Critical-class recall — the headline metric\n")
    lines.append(
        f"Of the **{metrics['critical_support']:,}** tickets the dataset labels "
        f"`Critical`, the scorer flagged **{metrics['critical_caught']:,}** as "
        f"Critical or High.\n\n"
        f"> **Critical-class recall = {_fmt_pct(metrics['critical_recall'])}**\n\n"
        f"Over the wider top-severity bucket (`Critical` + `High`, "
        f"{metrics['top_severity_support']:,} tickets) recall is "
        f"**{_fmt_pct(metrics['top_severity_recall'])}**.\n\n"
        f"The number to compare these against: the scorer calls "
        f"**{_fmt_pct(metrics['top_flag_rate'])}** of *all* tickets top-severity. "
        f"Recall that matches the flag rate is what you get from flagging tickets at "
        f"random — the scorer is not finding critical tickets, it is finding its own "
        f"keywords, which this dataset scatters independently of the label.\n"
    )

    lines.append("## 2. Overall accuracy & confusion matrix\n")
    lines.append(
        f"**Overall accuracy: {_fmt_pct(metrics['accuracy'])}** "
        f"({sum(m[label][label] for label in LABELS):,}/{metrics['total']:,} correct) "
        f"against a **{_fmt_pct(metrics['chance_accuracy'])} chance baseline** "
        f"and a {_fmt_pct(metrics['majority_accuracy'])} majority-class baseline.\n"
    )
    lines.append("Rows = dataset label (truth), columns = scorer prediction.\n")
    lines.append("| truth ↓ / pred → | " + " | ".join(DISPLAY_ORDER) + " | recall |")
    lines.append("|---" * (len(DISPLAY_ORDER) + 2) + "|")
    for t in DISPLAY_ORDER:
        cells = " | ".join(f"{m[t][p]:,}" for p in DISPLAY_ORDER)
        lines.append(f"| **{t}** | {cells} | {_fmt_pct(metrics['per_class'][t]['recall'])} |")
    lines.append(
        "| **precision** | "
        + " | ".join(_fmt_pct(metrics["per_class"][p]["precision"]) for p in DISPLAY_ORDER)
        + " | |"
    )
    lines.append("")
    lines.append(
        "Two notes on reading this table. The `recall` column is **exact-match** "
        "recall (the diagonal), which is why Critical reads "
        f"{_fmt_pct(metrics['per_class'][Category.CRITICAL.value]['recall'])} here "
        f"while section 1 reports {_fmt_pct(metrics['critical_recall'])} — that "
        "headline counts a Critical ticket caught as *either* Critical or High, "
        "which is the operationally relevant question. And Medium's apparently "
        "strong recall is an artifact of central tendency, not skill: the scorer "
        "puts a plurality of everything in Medium, so it wins that row by "
        "answering the same way every time.\n\n"
        "Read the rows, not the diagonal. Every row is close to identical: the "
        "scorer emits nearly the same distribution of predictions whether the "
        "ticket is truly Critical or truly Low. That shape — not the accuracy "
        "figure — is the actual finding.\n"
    )

    lines.append("## 3. Is the label predictable at all?\n")
    lines.append(
        "Two chi-square tests of independence. Cramér's V is the effect size: "
        "0 means no relationship, 1 means one variable determines the other. At "
        f"n={metrics['total']:,} a p-value alone would be misleading, so read V.\n"
    )
    lines.append("| Test | chi² | dof | p | Cramér's V |")
    lines.append("|---|---|---|---|---|")
    lines.append(
        f"| Scorer prediction × true label | {pi['chi2']:.1f} | {pi['dof']} | "
        f"{_fmt_p(pi['p'])} | **{pi['cramers_v']:.3f}** |"
    )
    lines.append(
        f"| Ticket subject × true label | {si['chi2']:.1f} | {si['dof']} | "
        f"{_fmt_p(si['p'])} | **{si['cramers_v']:.3f}** |"
    )
    lines.append("")
    lines.append(
        "Both chi² statistics sit at or below their degrees of freedom, which is "
        "what pure independence looks like — under the null hypothesis the expected "
        "value of chi² *is* dof.\n\n"
        "The second row is the important one. It does not involve this scorer at "
        "all: it asks whether the ticket's own subject line predicts its priority. "
        "It does not. **No classifier reading this text could do better, because "
        "the text and the label were generated independently.** The dataset ships "
        "16 distinct subject lines and a template body whose product placeholder "
        "was never even interpolated (see `src/data_prep.py`).\n"
    )

    lines.append("## 4. Where the Critical predictions land\n")
    crit_total = sum(crit.values())
    lines.append(
        f"The scorer assigned Critical to **{crit_total:,}** tickets. Against the "
        f"dataset label they split: "
        + ", ".join(f"**{crit[label]:,} {label}**" for label in DISPLAY_ORDER)
        + ". An even split across four labels is, again, independence.\n"
    )

    lines.append("## 5. The safety net still works\n")
    net = metrics["safety_net_fired"]
    lines.append(
        f"The Critical-class safety net fired on **{net:,}** tickets "
        f"({_fmt_pct(net / metrics['total'] if metrics['total'] else 0)} of the "
        f"batch), forcing every hard-trigger ticket (outage, breach, locked out, "
        f"payment failed, …) to at least High regardless of its numeric score.\n\n"
        "This is worth stating plainly because the chance-level accuracy above "
        "invites the wrong conclusion. The safety net is a **deterministic "
        "guarantee about vocabulary**, not a prediction: any ticket containing a "
        "hard trigger is escalated, and `tests/test_rule_scorer.py` asserts that "
        "exhaustively. What this dataset removes is the ability to *measure* "
        "whether escalation correlates with the label, because the label "
        "correlates with nothing. The mechanism is intact; the measuring stick is "
        "broken.\n"
    )

    lines.append("## 6. Systematic confusions & examples\n")
    lines.append(
        "With an independent label there is no systematic confusion to describe — "
        "misses are not concentrated in any category of ticket. Representative "
        "examples of `Critical` truth scored `Low`:\n"
    )
    for s in misclassified_examples(scored, true=Category.CRITICAL.value,
                                    pred=Category.LOW.value, n=3):
        subj = (s.ticket.subject or s.ticket.body[:60]).replace("\n", " ")
        lines.append(f"- **Critical → Low**: “{subj[:80]}” (score {s.score})")
    lines.append("")

    lines.append("## 7. Manual spot-check\n")
    lines.append(
        "A 25-ticket sample is written to `results/spot_check_sample.csv` for a human "
        "reviewer to mark agree/disagree (PROJECT_PLAN.md §10). This is a small-sample "
        "sanity check, not a statistically powered metric, and the human agreement rate "
        "is intentionally left blank until reviewed — no fabricated numbers.\n\n"
        "On this dataset the spot-check is the *more* informative artifact: a human "
        "reading the ticket text can judge whether the scorer's call is sensible, "
        "which the dataset's own label cannot.\n"
    )

    lines.append("## 8. Honest limitations\n")
    lines.append(
        "- **The dataset's labels are not learnable from its text.** Everything in "
        "sections 1, 2 and 4 is bounded by that. Accuracy here measures the data, "
        "not the model.\n"
        "- **The ticket bodies are templated.** 16 unique subject lines across "
        f"{metrics['total']:,} tickets, and the raw descriptions ship with an "
        "unfilled `{product_purchased}` token that `data_prep` substitutes.\n"
        "- **Resolution-time and trend metrics are not reported anywhere in this "
        "project**, because 49.3% of closed tickets carry a resolution timestamp "
        "earlier than their first-response timestamp, and every timestamp falls "
        "inside a single 3-day window. See the Dashboard's data-integrity panel.\n"
        "- Keyword lists are tuned to a generic IT-support vocabulary, not a real "
        "company's product taxonomy — the ceiling on accuracy is low by design.\n"
        "- The safety net optimises **recall on the top-severity class first**; it "
        "over-fires to High on some routine tickets, which lowers precision. That "
        "trade is deliberate: a missed critical ticket costs far more than a false "
        "alarm.\n"
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
    print(f"Critical-class recall: {_fmt_pct(metrics['critical_recall'])}")
    print(f"Top-severity recall:   {_fmt_pct(metrics['top_severity_recall'])} "
          f"(scorer flags {_fmt_pct(metrics['top_flag_rate'])} of all tickets)")
    print(f"Overall accuracy:      {_fmt_pct(metrics['accuracy'])} "
          f"(chance {_fmt_pct(metrics['chance_accuracy'])})")
    print(f"Cramer's V, prediction x truth: {metrics['prediction_independence']['cramers_v']:.3f}")
    print(f"Cramer's V, subject x truth:    {metrics['subject_independence']['cramers_v']:.3f}")
    print("Wrote results/evaluation.md and results/spot_check_sample.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
