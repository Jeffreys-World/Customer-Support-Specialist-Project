"""Stage 3 — the overnight batch job.

Simulates "tickets arriving overnight": read the processed dataset, run every
ticket through the rule-based scorer, attach a rationale + suggested queue, and
write one ``classified_tickets.json`` the Streamlit UI reads from. This is the
piece that replaces "click AI Assistant per ticket" with an already-sorted queue.

Rationale source, in priority order:
  1. If ``--with-rationale`` is passed AND an API key is available → live Claude
     rationale (llm_rationale.generate_rationale). On any per-ticket API error we
     fall back for that ticket rather than aborting the whole run.
  2. Otherwise → deterministic rule-based fallback (llm_rationale.fallback_*),
     so the job always produces a valid, sorted result with no external deps.

Run:
    python -m src.batch_classify                     # score-only (fallback rationale)
    python -m src.batch_classify --limit 500         # first 500 tickets (after sorting)
    python -m src.batch_classify --with-rationale    # live Claude (needs ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import List, Optional

from src.llm_rationale import (
    RationaleUnavailable,
    fallback_rationale,
    fallback_suggested_queue,
    generate_rationale,
)
from src.rule_scorer import score_many
from src.schema import ScoredTicket, Ticket

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "data" / "processed" / "tickets.csv"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "processed" / "classified_tickets.json"


def load_tickets(path: Path) -> List[Ticket]:
    """Read ``data/processed/tickets.csv`` into Ticket objects."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python src/data_prep.py` first to build it."
        )
    tickets: List[Ticket] = []
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            tickets.append(
                Ticket(
                    id=row["id"],
                    subject=row.get("subject", ""),
                    body=row.get("body", ""),
                    true_priority=(row.get("priority", "") or "").strip().lower(),
                    true_queue=row.get("queue", ""),
                    language=row.get("language", ""),
                    tags=[t for t in (row.get("tags", "") or "").split(";") if t],
                )
            )
    return tickets


def attach_rationales(
    scored: List[ScoredTicket], with_rationale: bool
) -> None:
    """Fill in ``rationale`` and ``suggested_queue`` on each scored ticket in place."""
    client = None
    if with_rationale:
        try:
            from src.llm_rationale import get_client

            client = get_client()
            print("Claude rationale layer enabled.")
        except RationaleUnavailable as exc:
            print(f"LLM layer unavailable ({exc}). Falling back to rule-based rationale.")
            with_rationale = False

    llm_failures = 0
    for s in scored:
        if with_rationale and client is not None:
            try:
                s.rationale, s.suggested_queue = generate_rationale(s, client=client)
                continue
            except Exception as exc:  # noqa: BLE001 - degrade per-ticket, don't abort
                llm_failures += 1
                if llm_failures <= 3:
                    print(f"  rationale failed for {s.ticket.id} ({exc}); using fallback")
        # Deterministic fallback (score-only path).
        s.rationale = fallback_rationale(s)
        s.suggested_queue = fallback_suggested_queue(s)

    if llm_failures:
        print(f"{llm_failures} ticket(s) fell back after an API error.")


def run(input_path: Path, output_path: Path, limit: Optional[int], with_rationale: bool) -> List[ScoredTicket]:
    tickets = load_tickets(input_path)
    scored = score_many(tickets)  # already sorted most-urgent first
    if limit is not None:
        scored = scored[:limit]

    attach_rationales(scored, with_rationale)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump([s.to_dict() for s in scored], fh, ensure_ascii=False, indent=2)

    _print_summary(scored, output_path)
    return scored


def _print_summary(scored: List[ScoredTicket], output_path: Path) -> None:
    from collections import Counter

    cats = Counter(s.category.value for s in scored)
    net = sum(1 for s in scored if s.safety_net_triggered)
    print(f"\nClassified {len(scored)} tickets -> {output_path.name}")
    print("Category distribution:")
    for cat in ("Critical", "High", "Medium", "Low"):
        print(f"  {cat:<9} {cats.get(cat, 0)}")
    print(f"Safety-net escalations: {net}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Batch-classify tickets for the triage UI.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None, help="Only classify the top-N tickets.")
    parser.add_argument(
        "--with-rationale",
        action="store_true",
        help="Use the live Claude rationale layer (requires ANTHROPIC_API_KEY).",
    )
    args = parser.parse_args(argv)
    run(args.input, args.output, args.limit, args.with_rationale)
    return 0


if __name__ == "__main__":
    sys.exit(main())
