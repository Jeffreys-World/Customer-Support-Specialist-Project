"""The committed demo sample must span all four priorities.

Why this has a test: ``--limit`` slices the head of an already-sorted list, so
``--limit 800`` returns the 800 most urgent tickets — every one of them Critical.
The first committed sample was built that way, which made the priority filter
demonstrate nothing on a fresh clone and rendered the dashboard as a single bar.
``--stratified`` exists to prevent that, and this test keeps it honest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.batch_classify import stratified_sample
from src.schema import Category, ScoredTicket, Ticket

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "data" / "processed" / "classified_tickets.sample.json"


def _fake_batch() -> list:
    """A skewed batch: plenty of Medium, very few Low."""
    out = []
    plan = [(Category.CRITICAL, 300), (Category.HIGH, 200), (Category.MEDIUM, 900), (Category.LOW, 60)]
    n = 0
    for category, count in plan:
        for _ in range(count):
            n += 1
            out.append(
                ScoredTicket(
                    ticket=Ticket(id=f"T{n:05d}", subject="s", body="b"),
                    score={Category.CRITICAL: 95, Category.HIGH: 70,
                           Category.MEDIUM: 45, Category.LOW: 20}[category],
                    category=category,
                )
            )
    return out


def test_sample_spans_all_four_priorities():
    picked = stratified_sample(_fake_batch(), size=200)
    present = {s.category for s in picked}
    assert present == set(Category), f"missing priorities: {set(Category) - present}"


def test_sample_is_sorted_most_urgent_first():
    """The UI renders tickets in file order and does not re-sort them."""
    picked = stratified_sample(_fake_batch(), size=200)
    keys = [(-s.category.rank, -s.score, s.ticket.id) for s in picked]
    assert keys == sorted(keys)


def test_sample_is_deterministic():
    batch = _fake_batch()
    first = [s.ticket.id for s in stratified_sample(batch, size=200)]
    second = [s.ticket.id for s in stratified_sample(batch, size=200)]
    assert first == second


def test_thin_category_still_represented():
    """A category smaller than the floor is taken whole rather than dropped."""
    picked = stratified_sample(_fake_batch(), size=200, floor=40)
    lows = [s for s in picked if s.category is Category.LOW]
    assert len(lows) >= 40  # only 60 Low exist in the batch; proportional would give ~9


def test_roughly_proportional_to_the_real_distribution():
    """The sample is a miniature of the batch, not an equal split.

    Medium is 62% of the fake batch, so it should dominate the sample too —
    an even four-way split would misrepresent what the queue actually looks like.
    """
    picked = stratified_sample(_fake_batch(), size=400)
    mediums = [s for s in picked if s.category is Category.MEDIUM]
    assert len(mediums) > len(picked) / 3  # clearly the largest bucket
    assert len(mediums) < len(picked)      # but not the only one


def test_never_takes_more_than_exists():
    picked = stratified_sample(_fake_batch(), size=99_999)
    assert len(picked) <= len(_fake_batch())
    assert len({s.ticket.id for s in picked}) == len(picked)  # no duplicates


@pytest.mark.skipif(not SAMPLE.exists(), reason="committed sample not present")
def test_committed_sample_has_every_priority():
    """Guards the actual file a fresh clone falls back to."""
    tickets = json.loads(SAMPLE.read_text(encoding="utf-8"))
    present = {t["category"] for t in tickets}
    assert present == {c.value for c in Category}, (
        f"committed sample only contains {sorted(present)} — regenerate with "
        "`python -m src.batch_classify --stratified 800 "
        "--output data/processed/classified_tickets.sample.json`"
    )

    keys = [(-Category(t["category"]).rank, -t["score"], t["id"]) for t in tickets]
    assert keys == sorted(keys), "committed sample is not sorted most-urgent-first"
