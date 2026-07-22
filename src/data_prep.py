"""Stage 1 — turn the raw Kaggle CSV into a clean, English-only working set.

The source dataset (``dataset-tickets-multi-lang-4-20k.csv``) is multilingual and
carries a lot of columns the triage pipeline never reads. This script:

  1. loads the raw CSV from ``data/raw/``,
  2. filters to English tickets only (keyword scoring can't work on German text —
     a stated scope limit, PROJECT_PLAN.md §5),
  3. normalises the ground-truth ``priority`` label to ``low``/``medium``/``high``,
  4. drops rows with no usable text,
  5. collapses ``tag_1..tag_8`` into a single ``;``-joined ``tags`` column,
  6. writes ``data/processed/tickets.csv`` with a stable ``id`` per ticket.

Run:  ``python src/data_prep.py``  (add ``--input`` to point at a different CSV).

The dataset labels top out at ``high`` — there is no ``critical`` label — so the
product's four-level scale is only introduced later, in the scorer. See the plan's
"Critical label" decision.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

import pandas as pd

# src/ lives one level below the repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "data" / "raw" / "dataset-tickets-multi-lang-4-20k.csv"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "processed" / "tickets.csv"

VALID_LABELS = {"low", "medium", "high"}
TAG_COLUMNS = [f"tag_{i}" for i in range(1, 9)]
OUTPUT_COLUMNS = ["id", "subject", "body", "priority", "queue", "language", "tags"]


def _join_tags(row: pd.Series) -> str:
    """Collapse the sparse tag_1..tag_8 columns into one ``;``-joined string."""
    tags: List[str] = []
    for col in TAG_COLUMNS:
        val = row.get(col)
        if isinstance(val, str) and val.strip():
            tags.append(val.strip())
    return ";".join(tags)


def prepare(input_path: Path, output_path: Path) -> pd.DataFrame:
    """Load, filter, clean, and write the processed ticket set. Returns the frame."""
    if not input_path.exists():
        raise FileNotFoundError(
            f"Raw dataset not found at {input_path}. Place the Kaggle CSV in data/raw/ "
            f"or pass --input. See README setup instructions."
        )

    df = pd.read_csv(input_path, dtype=str, keep_default_na=False)
    total = len(df)

    # 2. English only.
    df = df[df["language"].str.strip().str.lower() == "en"].copy()
    after_lang = len(df)

    # 3. Normalise the ground-truth priority label.
    df["priority"] = df["priority"].str.strip().str.lower()
    df = df[df["priority"].isin(VALID_LABELS)].copy()

    # 4. Require some usable text.
    df["subject"] = df["subject"].fillna("").str.strip()
    df["body"] = df["body"].fillna("").str.strip()
    df = df[(df["subject"] != "") | (df["body"] != "")].copy()

    # 5. Collapse tags.
    df["tags"] = df.apply(_join_tags, axis=1)

    # Carry queue/language through as ground truth for evaluation + the UI.
    df["queue"] = df.get("queue", "").fillna("").str.strip()
    df["language"] = df["language"].str.strip().str.lower()

    # 6. Stable id (positional, zero-padded) so re-runs are reproducible.
    df = df.reset_index(drop=True)
    df["id"] = [f"T{idx:05d}" for idx in range(len(df))]

    out = df[OUTPUT_COLUMNS]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)

    _print_summary(total, after_lang, out)
    return out


def _print_summary(total: int, after_lang: int, out: pd.DataFrame) -> None:
    print(f"Loaded {total} raw rows.")
    print(f"English-only: {after_lang}")
    print(f"Written {len(out)} tickets -> data/processed/tickets.csv")
    dist = out["priority"].value_counts().reindex(["high", "medium", "low"]).fillna(0)
    print("Priority distribution:")
    for label, count in dist.items():
        print(f"  {label:<7} {int(count)}")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare English-only ticket set.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    prepare(args.input, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
