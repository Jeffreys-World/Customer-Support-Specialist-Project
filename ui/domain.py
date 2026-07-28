"""Data access and queue logic for the triage console.

Moved here verbatim from ``app.py`` when the UI was split into a package: the
loader, the deterministic SLA clock, and the override log. They were correct and
already covered by tests, so the move is a relocation, not a rewrite —
``tests/test_app_smoke.py`` imports the same two helpers from this module now.

Nothing in here imports Streamlit's rendering surface beyond ``st.cache_data``,
so queue filtering and SLA maths stay testable without a browser.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import streamlit as st

from src.llm_rationale import QUEUE_OPTIONS as LLM_QUEUE_OPTIONS
from src.schema import Category

REPO_ROOT = Path(__file__).resolve().parents[1]

# Prefer the full generated batch; fall back to the committed demo sample so a
# fresh clone still has a working queue.
DATA_CANDIDATES = [
    REPO_ROOT / "data" / "processed" / "classified_tickets.json",
    REPO_ROOT / "data" / "processed" / "classified_tickets.sample.json",
]
OVERRIDE_LOG = REPO_ROOT / "results" / "override_log.csv"

# SLA target per priority, in hours. Policy, not presentation — see
# `ui.theme.PriorityToken` for the visual half.
SLA_HOURS: Dict[Category, int] = {
    Category.CRITICAL: 1,
    Category.HIGH: 4,
    Category.MEDIUM: 24,
    Category.LOW: 72,
}

# Re-exported, not redefined. `llm_rationale` owns this list because it is the
# enum the model's structured output is constrained to; a second copy in the UI
# would silently drift the moment a queue is added there. (`app.py` carried such
# a copy before the console was split into this package.)
QUEUE_OPTIONS = LLM_QUEUE_OPTIONS


# --- Loading ------------------------------------------------------------------

@st.cache_data
def load_tickets() -> List[Dict]:
    """Read the classified batch. Empty list if the batch job hasn't run."""
    for path in DATA_CANDIDATES:
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
    return []


@st.cache_data
def queues_in_use() -> List[str]:
    """Queues that actually appear in the loaded batch, in QUEUE_OPTIONS order.

    ``QUEUE_OPTIONS`` is the full set the rationale layer is allowed to suggest.
    Only a subset shows up in any given batch, so filter controls must be built
    from this instead — offering a queue with no tickets behind it gives the
    agent a filter that silently returns nothing.
    """
    present = {t.get("suggested_queue", "") for t in load_tickets()}
    return [q for q in QUEUE_OPTIONS if q in present]


def active_data_source() -> Optional[Path]:
    """Which file the queue is being served from — surfaced in Settings."""
    for path in DATA_CANDIDATES:
        if path.exists():
            return path
    return None


# --- Deterministic SLA clock --------------------------------------------------

def simulated_age_hours(ticket_id: str) -> float:
    """Deterministic pseudo-age so the SLA demo is stable across reruns.

    The dataset carries no timestamps, so intake time is simulated from a hash of
    the ticket id — clearly a demo aid, not real data. This is also the pattern
    ``ui.demo_context`` follows for requester identity and thread history.
    """
    digest = int(hashlib.sha256(ticket_id.encode()).hexdigest(), 16)
    return (digest % (48 * 60)) / 60.0  # 0–48 hours, in fractional hours


def sla_state(category: str, age_hours: float) -> str:
    target = SLA_HOURS[Category(category)]
    remaining = target - age_hours
    if remaining <= 0:
        return "⚠️ breached"
    if remaining <= target * 0.25:
        return f"⏳ {remaining:.1f}h left"
    return f"{remaining:.1f}h left"


def sla_breached(ticket: Dict) -> bool:
    return simulated_age_hours(ticket["id"]) >= SLA_HOURS[Category(ticket["category"])]


# --- Queue shaping ------------------------------------------------------------

def filter_tickets(
    tickets: Iterable[Dict],
    categories: Optional[Iterable[str]] = None,
    queues: Optional[Iterable[str]] = None,
    query: str = "",
    only_safety_net: bool = False,
) -> List[Dict]:
    """Apply the console's filter row. Empty/None filters mean 'no constraint'."""
    cats = set(categories) if categories else None
    qs = set(queues) if queues else None
    needle = (query or "").strip().lower()

    out = []
    for t in tickets:
        if cats is not None and t["category"] not in cats:
            continue
        if qs is not None and t.get("suggested_queue", "") not in qs:
            continue
        if only_safety_net and not t.get("safety_net_triggered"):
            continue
        if needle and needle not in f"{t.get('subject', '')} {t.get('body', '')}".lower():
            continue
        out.append(t)
    return out


def category_counts(tickets: Iterable[Dict]) -> Dict[str, int]:
    """Count per priority, always returning all four keys so KPI rows never gap."""
    counts = {c.value: 0 for c in Category}
    for t in tickets:
        counts[t["category"]] = counts.get(t["category"], 0) + 1
    return counts


def sort_key(ticket: Dict) -> tuple:
    """Most urgent first: priority rank, then score, then id for stability."""
    return (-Category(ticket["category"]).rank, -int(ticket.get("score", 0)), ticket["id"])


# --- Override log -------------------------------------------------------------

def log_override(ticket_id: str, ai_category: str, agent_category: str, action: str) -> None:
    """Append a confirm/adjust decision to results/override_log.csv."""
    OVERRIDE_LOG.parent.mkdir(parents=True, exist_ok=True)
    is_new = not OVERRIDE_LOG.exists()
    with open(OVERRIDE_LOG, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(["timestamp", "ticket_id", "ai_category", "agent_category", "action"])
        writer.writerow([
            dt.datetime.now().isoformat(timespec="seconds"),
            ticket_id, ai_category, agent_category, action,
        ])


def read_override_log() -> List[Dict[str, str]]:
    """Every logged agent decision, oldest first. Empty if nothing reviewed yet."""
    if not OVERRIDE_LOG.exists():
        return []
    with open(OVERRIDE_LOG, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def agreement_stats() -> Dict[str, object]:
    """Confirm-vs-override rates over the review log.

    This is the honest analogue of Zendesk's satisfaction panel: instead of
    customer CSAT (which this dataset has no basis for), it reports how often the
    agent agreed with the AI's priority — real data, generated by real use of the
    confirm/adjust control.
    """
    rows = read_override_log()
    total = len(rows)
    confirmed = sum(1 for r in rows if r.get("action") == "confirm")
    return {
        "total": total,
        "confirmed": confirmed,
        "overridden": total - confirmed,
        "agreement_pct": round(100 * confirmed / total) if total else None,
    }


def reviewed_recently(days: int = 30) -> List[Dict[str, str]]:
    """Decisions logged in the last N days — backs the 'Completed work' view."""
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    out = []
    for row in read_override_log():
        try:
            stamp = dt.datetime.fromisoformat(row["timestamp"])
        except (ValueError, KeyError):
            continue  # tolerate a hand-edited log rather than crashing the view
        if stamp >= cutoff:
            out.append(row)
    return list(reversed(out))  # newest first
