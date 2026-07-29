"""Stage 1 — turn the raw Kaggle CSV into a clean working set.

The source dataset (``customer_support_tickets.csv``, 8,469 rows) carries a much
richer schema than the multilingual set this project started on: ticket status,
channel, product, CSAT, and a genuine four-level priority label that includes
``Critical``. That last column is why the swap was worth doing — the previous
dataset topped out at ``high``, so the product's Critical level had no ground
truth to be measured against (see :meth:`src.schema.Category.ground_truth_bucket`,
which no longer has to collapse anything).

This script:

  1. loads the raw CSV from ``data/raw/``,
  2. substitutes the real product name into the ``{product_purchased}`` template
     placeholder that every row's description still carries (see below),
  3. normalises the ground-truth ``Ticket Priority`` label to the four-level scale,
  4. drops rows with no usable text,
  5. maps ``Ticket Type`` onto the queue vocabulary the rationale layer speaks,
  6. synthesises a ``tags`` column from real dataset fields,
  7. writes ``data/processed/tickets.csv`` with a stable ``id`` per ticket.

Run:  ``python src/data_prep.py``  (add ``--input`` to point at a different CSV).

## The placeholder substitution

Every one of the 8,469 descriptions ships with the literal, unfilled template
token ``{product_purchased}`` — the dataset was generated from templates and the
interpolation step was never run. Left alone it renders as
``"I'm having an issue with the {product_purchased}."`` in the queue, which looks
broken. We substitute the row's real ``Product Purchased`` value, which is both
closer to a genuine ticket and honest: the product name is real dataset content,
not invented. This does change the text the scorer reads, so evaluation numbers
must be computed after substitution, never carried over from the raw text.

## A warning about this dataset's labels

``Ticket Priority`` is statistically independent of the ticket text (chi-square at
or below degrees of freedom for every text/label pair). The scorer therefore runs
at chance on it. That is a property of the data, not a bug in the pipeline, and
``src/evaluate.py`` measures and reports it directly rather than hiding it. Do not
"fix" this by relabelling.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

import pandas as pd

from src.schema import Category

# src/ lives one level below the repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "data" / "raw" / "customer_support_tickets.csv"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "processed" / "tickets.csv"

# The four-level scale, matching Category's own values exactly. The previous
# dataset only had low/medium/high, so this list used to be a separate, smaller
# vocabulary that Category had to be collapsed onto.
VALID_LABELS = {c.value for c in Category}

PLACEHOLDER = "{product_purchased}"

# `Ticket Type` is this dataset's closest analogue to a routing queue. Mapping it
# onto the vocabulary `src.llm_rationale.QUEUE_OPTIONS` already speaks keeps the
# UI's queue filter and the rationale layer's enum talking about the same things.
TYPE_TO_QUEUE = {
    "Technical issue": "Technical Support",
    "Billing inquiry": "Billing and Payments",
    "Refund request": "Returns and Exchanges",
    "Cancellation request": "Customer Service",
    "Product inquiry": "Product Support",
}

OUTPUT_COLUMNS = [
    "id", "subject", "body", "priority", "queue",
    "status", "channel", "product", "ticket_type",
    "csat", "first_response_at", "resolved_at", "purchase_date",
    "requester_name", "requester_email", "tags",
]


def _fill_placeholder(body: str, product: str) -> str:
    """Substitute the real product name into the unfilled template token.

    Falls back to a bare "product" rather than leaving braces on screen if a row
    somehow has no product value.
    """
    if PLACEHOLDER not in body:
        return body
    return body.replace(PLACEHOLDER, product.strip() or "product")


def _build_tags(row: pd.Series) -> str:
    """A ``;``-joined tag string built from real dataset columns.

    The previous dataset shipped ``tag_1..tag_8``; this one has no tag column, so
    the UI's tag chips are fed from fields that genuinely describe the ticket —
    its type, the channel it arrived on, and the product it concerns. Nothing here
    is invented, and nothing here influences triage.
    """
    tags = [row.get("Ticket Type", ""), row.get("Ticket Channel", ""), row.get("Product Purchased", "")]
    return ";".join(t.strip() for t in tags if isinstance(t, str) and t.strip())


def prepare(input_path: Path, output_path: Path) -> pd.DataFrame:
    """Load, clean, and write the processed ticket set. Returns the frame."""
    if not input_path.exists():
        raise FileNotFoundError(
            f"Raw dataset not found at {input_path}. Place the Kaggle CSV in data/raw/ "
            f"or pass --input. See README setup instructions."
        )

    df = pd.read_csv(input_path, dtype=str, keep_default_na=False)
    total = len(df)

    # 2. Fill the template placeholder with the row's real product.
    df["body"] = [
        _fill_placeholder(str(b), str(p))
        for b, p in zip(df["Ticket Description"], df["Product Purchased"])
    ]
    df["subject"] = df["Ticket Subject"].fillna("").astype(str).str.strip()
    df["body"] = df["body"].str.strip()

    # 3. Normalise the ground-truth priority onto the four-level scale. The raw
    #    values are already title-case ("Critical"/"High"/...), but normalising
    #    defensively means a re-exported CSV with different casing still loads.
    df["priority"] = df["Ticket Priority"].fillna("").astype(str).str.strip().str.title()
    df = df[df["priority"].isin(VALID_LABELS)].copy()
    after_label = len(df)

    # 4. Require some usable text.
    df = df[(df["subject"] != "") | (df["body"] != "")].copy()

    # 5. Queue vocabulary.
    df["ticket_type"] = df["Ticket Type"].fillna("").astype(str).str.strip()
    df["queue"] = df["ticket_type"].map(TYPE_TO_QUEUE).fillna("General Inquiry")

    # 6. Tags from real fields.
    df["tags"] = df.apply(_build_tags, axis=1)

    # Carry the analytics columns through untouched. The dashboard reads these;
    # the scorer never does.
    df["status"] = df["Ticket Status"].fillna("").astype(str).str.strip()
    df["channel"] = df["Ticket Channel"].fillna("").astype(str).str.strip()
    df["product"] = df["Product Purchased"].fillna("").astype(str).str.strip()
    df["csat"] = df["Customer Satisfaction Rating"].fillna("").astype(str).str.strip()
    df["first_response_at"] = df["First Response Time"].fillna("").astype(str).str.strip()
    df["resolved_at"] = df["Time to Resolution"].fillna("").astype(str).str.strip()
    df["purchase_date"] = df["Date of Purchase"].fillna("").astype(str).str.strip()
    df["requester_name"] = df["Customer Name"].fillna("").astype(str).str.strip()
    df["requester_email"] = df["Customer Email"].fillna("").astype(str).str.strip()

    # 7. Stable id (positional, zero-padded) so re-runs are reproducible.
    df = df.reset_index(drop=True)
    df["id"] = [f"T{idx:05d}" for idx in range(len(df))]

    out = df[OUTPUT_COLUMNS]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)

    _print_summary(total, after_label, out)
    return out


def _print_summary(total: int, after_label: int, out: pd.DataFrame) -> None:
    print(f"Loaded {total} raw rows.")
    print(f"With a valid four-level priority label: {after_label}")
    print(f"Written {len(out)} tickets -> data/processed/tickets.csv")
    order = [c.value for c in (Category.CRITICAL, Category.HIGH, Category.MEDIUM, Category.LOW)]
    dist = out["priority"].value_counts().reindex(order).fillna(0)
    print("Priority distribution:")
    for label, count in dist.items():
        print(f"  {label:<9} {int(count)}")
    filled = int((~out["body"].str.contains(PLACEHOLDER, regex=False)).sum())
    print(f"Placeholder substituted in {filled}/{len(out)} descriptions.")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the processed ticket set.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    prepare(args.input, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
