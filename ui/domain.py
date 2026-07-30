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
from typing import Dict, Iterable, List, Optional, Tuple

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
    "csat", "first_response_at", "resolved_at", "resolution", "purchase_date",
]

# Derived completeness flags added to the frame: flag name -> the column whose
# blankness it reports. A mapping rather than two parallel lists so reordering
# cannot silently pair a flag with the wrong column. Named after what they
# measure — see `field_completeness` for why they are not "urgent"/"overdue".
COMPLETENESS_FLAGS: Dict[str, str] = {
    "awaiting_first_response": "first_response_at",
    "unresolved": "resolved_at",
}


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
        return pd.DataFrame(
            columns=ANALYTICS_COLUMNS + list(COMPLETENESS_FLAGS) + ["csat_value"]
        )

    for column in ANALYTICS_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""

    # csat arrives as a string ("" for the ~67% of tickets that are not closed).
    frame["csat_value"] = pd.to_numeric(frame["csat"], errors="coerce")

    # Completeness flags. These say only what they measure: no first-response
    # timestamp is recorded, no resolution timestamp is recorded. They are
    # deliberately not called "urgent" or "overdue" — `field_completeness` shows
    # both blanks are a pure function of `status`, so a flag implying urgency
    # would be dressing the status column up as a new signal. Overdue belongs to
    # `sla_breached`, which is at least honest about its clock being simulated.
    for flag, column in COMPLETENESS_FLAGS.items():
        frame[flag] = frame[column].fillna("").astype(str).str.strip() == ""
    return frame


# --- How the scorer decides priority (backs the console's explainer) ----------

def scorer_reference() -> Dict[str, object]:
    """The scorer's own rules, read out of the scorer.

    Backs the "How priority is decided" explainer. Every number, keyword and
    threshold here is imported from :mod:`src.rule_scorer` and
    :mod:`src.schema` rather than written out again, for the same reason
    :func:`data_integrity` measures instead of transcribing: a hand-copied
    weights table is wrong the first time anyone tunes the scorer, and an
    explanation that is confidently wrong is worse than no explanation. Retune
    the scorer and this panel re-renders correctly with no edit here.

    Returned shape is deliberately plain dicts and lists, so the renderer does no
    thinking and this is testable without Streamlit.
    """
    from src import rule_scorer as rs
    from src.schema import SCORE_BANDS

    def group(signals: Dict[str, List[str]]) -> List[Dict[str, object]]:
        return [{"name": name, "variants": list(variants), "count": len(variants)}
                for name, variants in signals.items()]

    return {
        "base": rs.BASE_SCORE,
        "max": 100,
        # Most urgent first, each with the score range that lands in it. The top
        # band is open-ended at 100; the rest stop one below the next floor up.
        "bands": [
            {
                "category": category.value,
                "emoji": category.emoji,
                "floor": floor,
                "ceiling": (100 if index == 0 else SCORE_BANDS[index - 1][1] - 1),
                "sla_hours": SLA_HOURS[category],
            }
            for index, (category, floor) in enumerate(SCORE_BANDS)
        ],
        # Weight tiers, heaviest first. `hard` and `extra` share a weight: both
        # are critical-strength keyword hits, and only `hard` also forces
        # escalation, which is the distinction the explainer has to make clear.
        "tiers": [
            {"label": "Critical signals", "weight": rs.CRITICAL_WEIGHT,
             "groups": group(rs.HARD_TRIGGERS) + group(rs.CRITICAL_EXTRA),
             "forces_escalation": True},
            {"label": "High signals", "weight": rs.HIGH_WEIGHT,
             "groups": group(rs.HIGH_SIGNALS), "forces_escalation": False},
            {"label": "Medium signals", "weight": rs.MEDIUM_WEIGHT,
             "groups": group(rs.MEDIUM_SIGNALS), "forces_escalation": False},
            {"label": "Low signals", "weight": rs.LOW_WEIGHT,
             "groups": group(rs.LOW_SIGNALS), "forces_escalation": False},
        ],
        "hard_triggers": group(rs.HARD_TRIGGERS),
        "repeat": {"weight": rs.REPEAT_WEIGHT, "variants": list(rs.REPEAT_SIGNALS)},
        "safety_net_floor": rs.HIGH_FLOOR,
        "safety_net_category": Category.HIGH.value,
    }


def scorer_worked_example(text: str) -> Dict[str, object]:
    """Run one sentence through the real scorer and return the arithmetic.

    The explainer's tables state the rules; this shows them producing a number, so
    a reader can check the addition themselves. It calls :func:`score_ticket` — the
    same function the batch job uses — rather than reproducing the sum, which means
    the example cannot claim a total the scorer would not actually give.
    """
    from src.rule_scorer import (
        CRITICAL_EXTRA, CRITICAL_WEIGHT, HARD_TRIGGERS, HIGH_SIGNALS, HIGH_WEIGHT,
        LOW_SIGNALS, LOW_WEIGHT, MEDIUM_SIGNALS, MEDIUM_WEIGHT, REPEAT_WEIGHT,
        BASE_SCORE, score_ticket,
    )
    from src.schema import Ticket

    scored = score_ticket(Ticket(id="example", subject="", body=text))

    # Attribute each fired signal back to the weight that produced it, so the
    # breakdown lines add up to the score shown beside them.
    weights = [
        (HARD_TRIGGERS, CRITICAL_WEIGHT, True),
        (CRITICAL_EXTRA, CRITICAL_WEIGHT, False),
        (HIGH_SIGNALS, HIGH_WEIGHT, False),
        (MEDIUM_SIGNALS, MEDIUM_WEIGHT, False),
        (LOW_SIGNALS, LOW_WEIGHT, False),
    ]
    lines: List[Dict[str, object]] = []
    for name in scored.matched_signals:
        if name == "repeat-contact":
            lines.append({"signal": name, "weight": REPEAT_WEIGHT, "hard": False})
            continue
        for group, weight, hard in weights:
            if name in group:
                lines.append({"signal": name, "weight": weight, "hard": hard})
                break

    from src.rule_scorer import HIGH_FLOOR

    # What the keywords alone add up to, before the 0-100 clamp and before the net.
    raw = BASE_SCORE + sum(int(line["weight"]) for line in lines)
    return {
        "text": text,
        "base": BASE_SCORE,
        "lines": lines,
        "raw": raw,
        "score": scored.score,
        "category": scored.category.value,
        "safety_net_triggered": scored.safety_net_triggered,
        # Two different things, and the explainer shows them differently:
        "clamped": raw > 100,
        # ...and this is the one that demonstrates the net doing work — keyword
        # mass alone left it below High, and the net is what lifted it.
        "lifted_by_net": scored.safety_net_triggered and min(raw, 100) < HIGH_FLOOR,
    }


def safety_net_stats() -> Dict[str, object]:
    """How often the safety net actually fired on the loaded batch.

    The explainer states a rule; this is the evidence that the rule ran. Measured
    from the batch on every render, so it cannot go stale the way a figure quoted
    from a one-off analysis would.
    """
    from src.rule_scorer import HIGH_FLOOR

    tickets = load_tickets()
    total = len(tickets)
    fired = [t for t in tickets if t.get("safety_net_triggered")]
    lifted = [t for t in fired if int(t.get("score", 0)) == HIGH_FLOOR]
    return {
        "total": total,
        "fired": len(fired),
        "rate": len(fired) / total if total else 0.0,
        # Tickets sitting exactly at the floor are the ones the net actually
        # rescued: their keyword mass alone put them below High.
        "lifted_to_floor": len(lifted),
        "by_category": {
            category.value: sum(1 for t in fired if t.get("category") == category.value)
            for category in Category
        },
    }


# --- Field completeness -------------------------------------------------------

# Which ``status`` values are expected to populate each partially-filled
# operational field. This is a claim about the data, so `field_completeness`
# re-verifies it against the loaded batch on every call instead of trusting the
# comment — if a future dataset breaks the pattern, the panel says so.
COMPLETENESS_FIELDS: Dict[str, Tuple[str, ...]] = {
    "first_response_at": ("Closed", "Pending Customer Response"),
    "resolved_at": ("Closed",),
    "resolution": ("Closed",),
    "csat": ("Closed",),
}


def resolution_state(ticket: Dict) -> str:
    """Display label for a ticket's resolution, so the field is never just blank.

    Three states rather than two, because "no note" and "not yet resolved" are
    different facts and a batch generated before the ``resolution`` passthrough
    has the first without the second.
    """
    if str(ticket.get("resolution", "") or "").strip():
        return "Resolved"
    if str(ticket.get("status", "") or "").strip() == "Closed":
        return "Closed, no note recorded"
    return "Not yet resolved"


def field_completeness() -> List[Dict[str, object]]:
    """Fill rate per partially-populated field, and whether ``status`` explains it.

    This is the honest form of a "missing first response" flag. The tempting
    version of that flag — *no first-response timestamp AND status is Open* —
    fires on exactly the Open tickets and nothing else, so it restates the status
    column under a name ("urgent", "needs response") that implies new
    information. Rather than ship that, this measures the redundancy and reports
    it: ``explained_by_status`` is True when a field's blanks are perfectly
    predicted by status, which on this dataset is true for all four fields.

    Consequence worth stating plainly: no "days open" or "overdue" metric can be
    built from these blanks. The dataset carries no ticket-creation timestamp at
    all (only ``purchase_date``, which precedes every ticket by years), which is
    why `simulated_age_hours` exists and labels itself a demo clock.
    """
    frame = tickets_frame()
    if frame.empty:
        return []

    status = frame["status"].fillna("").astype(str).str.strip()
    rows: List[Dict[str, object]] = []
    for column, populating in COMPLETENESS_FIELDS.items():
        filled = frame[column].fillna("").astype(str).str.strip() != ""
        expected = status.isin(populating)
        rows.append({
            "field": column,
            "filled": int(filled.sum()),
            "blank": int((~filled).sum()),
            "total": int(len(frame)),
            "coverage": float(filled.mean()),
            "populating_status": list(populating),
            "mismatches": int((filled != expected).sum()),
            "explained_by_status": bool((filled == expected).all()),
        })
    return rows


# --- Dashboard analytics, continued -------------------------------------------

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


# Vocabulary a genuine support resolution note would be expected to draw on. Used
# only to measure whether this dataset's `Resolution` column does — it is not a
# scoring signal and must never become one (the scorer reads `rule_scorer`'s sets
# and nothing else).
SUPPORT_TERMS: Tuple[str, ...] = (
    "refund", "replac", "account", "order", "ship", "return", "charge", "bill",
    "password", "reset", "warrant", "repair", "install", "updat", "driver",
    "setting", "support", "resolv", "fix", "troubleshoot", "escalat", "credit",
    "invoice", "subscription",
)


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
        "resolution_notes": 0,
        "resolution_unique": 0,
        "resolution_mentions_product": 0,
        "resolution_domain_terms": 0,
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

    # 3. Is the closing note actually about the ticket it closes? Two cheap,
    #    falsifiable checks: does it use any support vocabulary at all, and does
    #    it ever name the product it supposedly fixed. Both come out near zero,
    #    which is why the workspace shows resolution *state* and not this prose.
    notes = frame["resolution"].fillna("").astype(str).str.strip()
    present = notes[notes != ""]
    out["resolution_notes"] = int(len(present))
    if len(present):
        out["resolution_unique"] = int(present.nunique())
        lowered = present.str.lower()
        out["resolution_domain_terms"] = int(
            lowered.apply(lambda note: any(term in note for term in SUPPORT_TERMS)).sum()
        )
        products = frame.loc[present.index, "product"].fillna("").astype(str)
        out["resolution_mentions_product"] = int(sum(
            1 for note, product in zip(lowered, products)
            if product.strip() and product.split()[0].lower() in note
        ))

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
