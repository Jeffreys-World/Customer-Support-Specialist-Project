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

# Queue sort vocabulary. Lives here rather than as a literal in the filter row so
# the Settings page can offer the same list as a default without the two drifting.
SORT_OPTIONS: List[str] = ["Recommended", "Oldest first", "Highest score"]


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


# --- Dashboard analytics ------------------------------------------------------

# Columns the Dashboard reads. A batch generated before the dataset swap has
# none of them, so the frame guarantees they exist rather than making every call
# site defend itself — `frame.get(missing)` returns None, and passing None into
# `pd.to_datetime` yields None rather than an empty Series, which then blows up
# on `.notna()`. Guaranteeing the columns once is the fix; see
# `test_dashboard_survives_a_pre_swap_batch`.
ANALYTICS_COLUMNS = [
    "subject", "true_priority", "status", "channel", "product", "ticket_type",
    "csat", "first_response_at", "resolved_at", "purchase_date",
]


@st.cache_data
def tickets_frame() -> "pd.DataFrame":
    """The loaded batch as a DataFrame, for the Dashboard's charts.

    Kept out of the queue path deliberately: the ticket list and detail views
    work on plain dicts and must stay free of a pandas import on the hot path.
    Only the Dashboard pays for this, and it is cached.

    Every column in :data:`ANALYTICS_COLUMNS` is guaranteed present (empty string
    when the loaded batch predates the dataset swap), so downstream chart code
    can index directly and simply render an empty state.
    """
    import pandas as pd

    frame = pd.DataFrame(load_tickets())
    if frame.empty:
        return pd.DataFrame(columns=ANALYTICS_COLUMNS + ["csat_value"])

    for column in ANALYTICS_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""

    # csat arrives as a string ("" for the ~67% of tickets that are not closed).
    frame["csat_value"] = pd.to_numeric(frame["csat"], errors="coerce")
    return frame


def count_by(column: str) -> Dict[str, int]:
    """Value counts for one column, descending. Empty strings are dropped."""
    frame = tickets_frame()
    if frame.empty or column not in frame:
        return {}
    series = frame[column].fillna("").astype(str).str.strip()
    series = series[series != ""]
    return series.value_counts().to_dict()


def csat_summary() -> Dict[str, object]:
    """Average satisfaction and, just as importantly, its coverage.

    Coverage is reported alongside the mean everywhere it is shown. Only closed
    tickets carry a rating in this dataset — roughly a third of the batch — so a
    bare average would silently describe a minority of the queue.
    """
    frame = tickets_frame()
    if frame.empty:
        return {"mean": None, "rated": 0, "total": 0, "coverage": 0.0, "histogram": {}}
    values = frame["csat_value"].dropna()
    total = len(frame)
    hist = {int(k): int(v) for k, v in values.value_counts().sort_index().items()}
    return {
        "mean": round(float(values.mean()), 2) if len(values) else None,
        "rated": int(len(values)),
        "total": total,
        "coverage": len(values) / total if total else 0.0,
        "histogram": hist,
    }


def status_summary() -> Dict[str, object]:
    """Open / pending / closed counts and the unresolved rate.

    The unresolved rate is what stands in for "average resolution time": it is
    computable from a status column that is fully populated, where a duration is
    not computable from timestamps that run backwards. See :func:`data_integrity`.
    """
    counts = count_by("status")
    total = sum(counts.values())
    closed = counts.get("Closed", 0)
    return {
        "counts": counts,
        "total": total,
        "closed": closed,
        "unresolved": total - closed,
        "unresolved_rate": (total - closed) / total if total else 0.0,
    }


def data_integrity() -> Dict[str, object]:
    """Measured data-quality facts backing the Dashboard's integrity panel.

    Every number the panel prints is computed here from the loaded batch rather
    than hardcoded from a one-off analysis, so the panel stays true if the batch
    is regenerated or the dataset is swapped again.
    """
    import pandas as pd

    from src.evaluate import independence

    frame = tickets_frame()
    out: Dict[str, object] = {
        "total": len(frame),
        "subject_independence": None,
        "unique_subjects": 0,
        "timestamp_pairs": 0,
        "timestamp_inverted": 0,
        "timestamp_inverted_rate": 0.0,
        "response_days": 0,
        "csat": csat_summary(),
    }
    if frame.empty:
        return out

    # 1. Is the ground-truth label predictable from the ticket's own subject?
    pairs = [(s, p) for s, p in zip(frame["subject"], frame["true_priority"]) if s and p]
    out["subject_independence"] = independence(pairs) if pairs else None
    out["unique_subjects"] = int(frame["subject"].nunique())

    # 2. Do the timestamps describe a coherent timeline?
    first = pd.to_datetime(frame["first_response_at"], errors="coerce")
    resolved = pd.to_datetime(frame["resolved_at"], errors="coerce")
    both = first.notna() & resolved.notna()
    pair_count = int(both.sum())
    inverted = int(((resolved < first) & both).sum())
    out["timestamp_pairs"] = pair_count
    out["timestamp_inverted"] = inverted
    out["timestamp_inverted_rate"] = inverted / pair_count if pair_count else 0.0
    spread = first.dropna()
    out["response_days"] = int(spread.dt.normalize().nunique()) if len(spread) else 0

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
