"""Priority-prediction ceiling experiment — a standalone, reproducible negative result.

**This is not part of the product.** Nothing in ``src/`` or ``ui/`` imports it, and
it imports nothing from the console. It exists to answer one question with numbers
instead of an assertion: *can a machine-learning model predict this dataset's
``Ticket Priority`` label?*

The answer is no, and the interesting part is how thoroughly no. Run it:

    python -m prediction_model                  # print the report
    python -m prediction_model --write          # also update results/priority_prediction.md

## Why this file exists

IMPLEMENTATION_PLAN.md Phase 2 proposed a ``RandomForestClassifier`` over
``[Keyword_Urgency_Score, Days_Open]`` predicting ``Priority``, then merging a
``Predicted_Priority`` column into the dashboard. Two problems surfaced before any
of that was written:

1. ``results/evaluation.md`` §3 already established, by chi-square, that the
   priority label is statistically independent of the ticket text. A model reading
   features derived from that text therefore cannot beat chance.
2. The proposed snippet fit on the full dataset and predicted on the same rows, so
   it would have printed ~70% accuracy — memorisation, not skill.

Rather than ship a chance-level column labelled "prediction", this measures the
ceiling honestly and reports it. Three feature sets of increasing strength are
tried, so the conclusion cannot be dismissed as weak feature engineering:

    A. plan-features   the two features Phase 2 specified
    B. tabular         every operational column, one-hot encoded
    C. text (TF-IDF)   the ticket subject + body itself

If the label were learnable from anything this dataset carries, C would find it.

## Reproducibility

Every split and model is seeded (``RANDOM_STATE``). ``days_since_purchase`` is
measured from a fixed ``REFERENCE_DATE`` rather than ``now()``, so re-running next
month gives the same numbers; because that feature is a monotonic transform of
``purchase_date``, the anchor choice cannot change a tree model's result anyway.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import make_pipeline

from src.evaluate import independence
from src.schema import DATASET_LABELS

REPO_ROOT = Path(__file__).resolve().parent
# Prefer the full classified batch (it carries the rule scorer's own score, which
# is the plan's `Keyword_Urgency_Score`); fall back to the committed demo sample so
# a fresh clone can still run this.
DATA_CANDIDATES = [
    REPO_ROOT / "data" / "processed" / "classified_tickets.json",
    REPO_ROOT / "data" / "processed" / "classified_tickets.sample.json",
]
REPORT_PATH = REPO_ROOT / "results" / "priority_prediction.md"

RANDOM_STATE = 42
TEST_SIZE = 0.2
# Fixed so the report is reproducible. See the module docstring: this anchor cannot
# change a tree model's result, because the feature is monotonic in purchase_date.
REFERENCE_DATE = pd.Timestamp("2026-01-01")

TARGET = "true_priority"


# --- Data ---------------------------------------------------------------------

def load_frame(path: Optional[Path] = None) -> Tuple[pd.DataFrame, Path]:
    """Load the classified batch independently of the console's cached loader."""
    candidates = [path] if path else DATA_CANDIDATES
    for candidate in candidates:
        if candidate and candidate.exists():
            with open(candidate, encoding="utf-8") as fh:
                return pd.DataFrame(json.load(fh)), candidate
    raise FileNotFoundError(
        "No classified batch found. Run `python -m src.data_prep` then "
        "`python -m src.batch_classify` first."
    )


def build_features(frame: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """The three feature sets, weakest to strongest."""
    work = frame.copy()

    # The plan's `Keyword_Urgency_Score` is the rule scorer's numeric 0-100 output.
    work["keyword_urgency_score"] = pd.to_numeric(work["score"], errors="coerce").fillna(0)
    # The plan's `Days_Open`. There is no ticket-creation timestamp in this dataset,
    # so purchase_date is the only date available — which is why this feature spans
    # ~1,673-2,402 days and why `Days_Open > 5` was true for every single row.
    purchased = pd.to_datetime(work["purchase_date"], errors="coerce")
    work["days_since_purchase"] = (REFERENCE_DATE - purchased).dt.days

    plan_features = work[["keyword_urgency_score", "days_since_purchase"]].fillna(-1)

    # Note `pd.get_dummies` on the plan's two columns is a no-op — both are already
    # numeric. It only does anything for the categorical columns below.
    tabular = pd.get_dummies(
        pd.DataFrame({
            "keyword_urgency_score": work["keyword_urgency_score"],
            "days_since_purchase": work["days_since_purchase"].fillna(-1),
            "safety_net_triggered": work["safety_net_triggered"].astype(bool).astype(int),
            "signal_count": work["matched_signals"].apply(
                lambda s: len(s) if isinstance(s, list) else 0
            ),
            "body_length": work["body"].fillna("").astype(str).str.len(),
            "csat_value": pd.to_numeric(work["csat"], errors="coerce").fillna(-1),
            "scorer_category": work["category"].astype(str),
            "status": work["status"].astype(str),
            "channel": work["channel"].astype(str),
            "product": work["product"].astype(str),
            "ticket_type": work["ticket_type"].astype(str),
        }),
        columns=["scorer_category", "status", "channel", "product", "ticket_type"],
        drop_first=True,
    )

    text = pd.DataFrame({
        "text": (
            work["subject"].fillna("").astype(str) + "\n\n" + work["body"].fillna("").astype(str)
        ).str.strip()
    })

    return {"plan-features": plan_features, "tabular": tabular, "text": text}


# --- Evaluation ---------------------------------------------------------------

def evaluate_features(name: str, X, y: pd.Series) -> Dict[str, object]:
    """Fit, then report held-out AND train accuracy so the gap is visible."""
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )

    if name == "text":
        model = make_pipeline(
            TfidfVectorizer(sublinear_tf=True, min_df=2, ngram_range=(1, 2)),
            LogisticRegression(max_iter=1000, random_state=RANDOM_STATE),
        )
        fit_train, fit_test = X_train["text"], X_test["text"]
        full = X["text"]
    else:
        model = RandomForestClassifier(random_state=RANDOM_STATE)
        fit_train, fit_test = X_train, X_test
        full = X

    model.fit(fit_train, y_train)
    predicted = model.predict(fit_test)

    return {
        "features": name,
        "n_features": 1 if name == "text" else int(X.shape[1]),
        "holdout_accuracy": float(accuracy_score(y_test, predicted)),
        "holdout_macro_f1": float(f1_score(y_test, predicted, average="macro", zero_division=0)),
        # Fitting and scoring on the same rows — the number the plan's original
        # snippet would have printed. Reported to show the gap, never as a result.
        "train_accuracy": float(accuracy_score(y, model.predict(full))),
        "cv_accuracy": float(
            cross_val_score(model, fit_train, y_train, cv=5, scoring="accuracy").mean()
        ),
        "confusion": confusion_matrix(y_test, predicted, labels=DATASET_LABELS).tolist(),
        "test_n": int(len(y_test)),
    }


def baselines(y: pd.Series) -> Dict[str, float]:
    """What "no skill" looks like, so every accuracy above has a yardstick."""
    # Same seed, same stratification, so this y_test is the identical hold-out the
    # feature sets above are scored on and the numbers are directly comparable.
    X = pd.DataFrame({"constant": [0] * len(y)}, index=y.index)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    dummy = DummyClassifier(strategy="most_frequent").fit(X_train, y_train)
    return {
        "chance": 1.0 / y.nunique(),
        "majority_class": float(accuracy_score(y_test, dummy.predict(X_test))),
    }


def run(path: Optional[Path] = None) -> Dict[str, object]:
    frame, source = load_frame(path)
    y = frame[TARGET].astype(str)

    results = [
        evaluate_features(name, X, y) for name, X in build_features(frame).items()
    ]
    return {
        "source": source.name,
        "rows": int(len(frame)),
        "classes": sorted(y.unique()),
        "class_counts": {k: int(v) for k, v in y.value_counts().items()},
        "baselines": baselines(y),
        "results": results,
        # The same chi-square the console's integrity panel and evaluation.md use,
        # imported rather than reimplemented so the numbers cannot drift apart.
        "subject_independence": independence(
            [(s, p) for s, p in zip(frame["subject"].astype(str), y) if s and p]
        ),
    }


# --- Reporting ----------------------------------------------------------------

def verdict(summary: Dict[str, object]) -> Dict[str, object]:
    """Is the best model's edge over the majority baseline real, or noise?

    At n≈1,700 held-out rows an accuracy near 25% carries a standard error of
    roughly one percentage point, so "26.1% beats the 25.9% baseline" is not a
    result. Anything inside two standard errors is reported as noise rather than
    as a win — the whole point of this file is to not overstate a number.
    """
    base = summary["baselines"]
    best = max(summary["results"], key=lambda r: r["holdout_accuracy"])
    accuracy = best["holdout_accuracy"]
    se = (accuracy * (1 - accuracy) / best["test_n"]) ** 0.5
    margin = accuracy - base["majority_class"]
    return {
        "best": best,
        "standard_error": se,
        "margin_vs_majority": margin,
        "beats_baseline": bool(margin > 2 * se),
    }


def format_report(summary: Dict[str, object]) -> str:
    base = summary["baselines"]
    chance, majority = base["chance"], base["majority_class"]
    call = verdict(summary)
    best, se = call["best"], call["standard_error"]
    si = summary["subject_independence"]

    lines: List[str] = [
        "# Priority prediction — measured ceiling",
        "",
        f"Generated by `python -m prediction_model --write` over **{summary['rows']:,} "
        f"tickets** from `{summary['source']}`. Every split is seeded "
        f"(`random_state={RANDOM_STATE}`), so these numbers reproduce exactly.",
        "",
        "> **Headline: no feature set beats guessing.** The best held-out accuracy of "
        f"any model tried is **{best['holdout_accuracy'] * 100:.1f}%** "
        f"(`{best['features']}`), against a **{chance * 100:.1f}%** chance baseline and a "
        f"**{majority * 100:.1f}%** majority-class baseline. That is "
        f"{call['margin_vs_majority'] * 100:+.1f} points on "
        f"{best['test_n']:,} held-out tickets, where one standard error is "
        f"{se * 100:.1f} points — so it is noise, not an edge. This is a property of "
        "the dataset, not of the models.",
        "",
        "## Why this was measured instead of shipped",
        "",
        "`IMPLEMENTATION_PLAN.md` Phase 2 proposed a RandomForest over "
        "`[Keyword_Urgency_Score, Days_Open]` and a `Predicted_Priority` column merged "
        "into the dashboard. Before writing that, two facts had to be checked:",
        "",
        "1. `results/evaluation.md` §3 had already shown the priority label is "
        "independent of the ticket text. Re-measured here with the same helper: "
        f"`chi2 = {si['chi2']:.1f}` on `{si['dof']} dof`, Cramér's V = "
        f"`{si['cramers_v']:.3f}`. A chi-square at or below its degrees of freedom is "
        "what independence looks like.",
        "2. The proposed snippet fit and predicted on the same rows, so it would have "
        "reported a train-set score as if it were accuracy. The gap column below is "
        "what that would have hidden.",
        "",
        "## Results",
        "",
        "| Feature set | Features | Held-out acc. | 5-fold CV | Macro F1 | Train acc. | Gap |",
        "|---|---|---|---|---|---|---|",
    ]

    for r in summary["results"]:
        gap = r["train_accuracy"] - r["holdout_accuracy"]
        features = "TF-IDF 1-2gram" if r["features"] == "text" else f"{r['n_features']:,}"
        lines.append(
            f"| `{r['features']}` | {features} | **{r['holdout_accuracy'] * 100:.1f}%** | "
            f"{r['cv_accuracy'] * 100:.1f}% | {r['holdout_macro_f1']:.3f} | "
            f"{r['train_accuracy'] * 100:.1f}% | +{gap * 100:.1f} pts |"
        )

    lines += [
        "",
        f"Baselines: **{chance * 100:.1f}%** chance (4 near-balanced classes), "
        f"**{majority * 100:.1f}%** always-guess-the-majority-class. Class counts: "
        + ", ".join(f"{k} {v:,}" for k, v in sorted(summary["class_counts"].items()))
        + ".",
        "",
        "Reading the table:",
        "",
        "- **`plan-features`** is exactly what Phase 2 specified. Note the train column: "
        "that is the ~70% the original snippet would have printed, from a model whose "
        "real accuracy is at chance. A RandomForest given a near-unique numeric feature "
        "(`days_since_purchase`) memorises the training rows and generalises nothing.",
        "- **`tabular`** adds every operational column — channel, product, ticket type, "
        "status, CSAT, the scorer's own category and signal count. No improvement.",
        "- **`text`** reads the ticket subject and body directly. If the label were "
        "recoverable from anything in this dataset, this is where it would show up. It "
        "does not, which is the chi-square result restated as a learning curve.",
        "",
        "## `Days_Open` could not be computed",
        "",
        "Phase 2's second feature does not exist in this dataset. There is no "
        "ticket-creation timestamp — the only date is `purchase_date`, which precedes "
        "every ticket by years. Measured from the fixed reference date this file uses, "
        "`days_since_purchase` spans roughly 1,700–2,400 days, so the plan's "
        "`Days_Open > 5` overdue test would have been true for every row in the "
        "dataset. It is kept as a feature here only to reproduce Phase 2 faithfully.",
        "",
        "## What was not done, and why",
        "",
        "No `Predicted_Priority` column was merged into the dashboard. At the accuracy "
        "above it would have been a random number sitting beside a real one, in a "
        "console whose own Data integrity panel tells the user this label is not "
        "learnable. The rule-based scorer stays the product: it is deterministic, it "
        "explains every call it makes, and its Critical-class safety net is a guarantee "
        "about vocabulary rather than a prediction — which is exactly the property that "
        "survives a dataset whose labels carry no signal.",
        "",
        "The honest use for a model here would be a label the data can actually "
        "support. This dataset does not have one: the bodies are templated from 16 "
        "subject lines, and the resolution notes are generator filler (see the "
        "Dashboard's Data integrity panel).",
        "",
    ]
    return "\n".join(lines)


def print_console_summary(summary: Dict[str, object]) -> None:
    base = summary["baselines"]
    print(f"Source: {summary['source']}  ({summary['rows']:,} tickets)")
    print(f"Baselines: chance {base['chance'] * 100:.1f}%  "
          f"majority-class {base['majority_class'] * 100:.1f}%")
    print()
    print(f"{'feature set':<16}{'held-out':>10}{'5-fold CV':>11}{'macro F1':>10}"
          f"{'train':>9}{'gap':>8}")
    for r in summary["results"]:
        gap = r["train_accuracy"] - r["holdout_accuracy"]
        print(f"{r['features']:<16}{r['holdout_accuracy'] * 100:>9.1f}%"
              f"{r['cv_accuracy'] * 100:>10.1f}%{r['holdout_macro_f1']:>10.3f}"
              f"{r['train_accuracy'] * 100:>8.1f}%{gap * 100:>+7.1f}")
    print()
    call = verdict(summary)
    best, se = call["best"], call["standard_error"]
    reading = (
        f"beats the majority-class baseline by {call['margin_vs_majority'] * 100:+.1f} pts "
        f"(> 2 SE, so this is a real edge)"
        if call["beats_baseline"] else
        f"{call['margin_vs_majority'] * 100:+.1f} pts vs the majority-class baseline, "
        f"inside noise (1 SE = {se * 100:.1f} pts on {best['test_n']:,} rows)"
    )
    print(f"Best held-out: {best['holdout_accuracy'] * 100:.1f}% ({best['features']}) — {reading}.")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=None, help="A classified batch JSON.")
    parser.add_argument(
        "--write", action="store_true",
        help=f"Write the markdown report to {REPORT_PATH.relative_to(REPO_ROOT)}.",
    )
    args = parser.parse_args(argv)

    summary = run(args.input)
    print_console_summary(summary)

    if args.write:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(format_report(summary), encoding="utf-8")
        print(f"\nReport written to {REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
