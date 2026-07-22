"""Stage 4 — Jordan's Ticket Triage Assistant (Streamlit UI).

The payoff of the whole pipeline: instead of opening an unsorted queue and
running an AI assistant ticket-by-ticket, Jordan opens an already-sorted list.
This app reads the batch job's ``classified_tickets.json`` and renders:

  * a queue view sorted by priority + urgency score, with Zendesk-ish accents
    and a (simulated) SLA countdown;
  * a detail view with the plain-language rationale and suggested queue;
  * a confirm / adjust control — the agent always has final say — that logs
    every override to ``results/override_log.csv`` for the manual spot-check.

Run:  ``streamlit run app.py``
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent
# Prefer the full generated batch; fall back to the committed demo sample.
DATA_CANDIDATES = [
    REPO_ROOT / "data" / "processed" / "classified_tickets.json",
    REPO_ROOT / "data" / "processed" / "classified_tickets.sample.json",
]
OVERRIDE_LOG = REPO_ROOT / "results" / "override_log.csv"

# Product priority scale → (emoji, accent colour, SLA target in hours).
CATEGORY_STYLE: Dict[str, Dict[str, object]] = {
    "Critical": {"emoji": "🔴", "color": "#d32f2f", "sla_hours": 1},
    "High": {"emoji": "🟠", "color": "#f57c00", "sla_hours": 4},
    "Medium": {"emoji": "🟡", "color": "#fbc02d", "sla_hours": 24},
    "Low": {"emoji": "🟢", "color": "#388e3c", "sla_hours": 72},
}
CATEGORY_ORDER = ["Critical", "High", "Medium", "Low"]
QUEUE_OPTIONS = [
    "Technical Support", "IT Support", "Product Support", "Customer Service",
    "Billing and Payments", "Service Outages and Maintenance",
    "Returns and Exchanges", "Sales and Pre-Sales", "Human Resources", "General Inquiry",
]


# --- Data loading ------------------------------------------------------------

@st.cache_data
def load_tickets() -> List[Dict]:
    for path in DATA_CANDIDATES:
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
    return []


def simulated_age_hours(ticket_id: str) -> float:
    """Deterministic pseudo-age so the SLA demo is stable across reruns.

    The dataset carries no timestamps, so intake time is simulated from a hash of
    the ticket id — clearly a demo aid, not real data.
    """
    digest = int(hashlib.sha256(ticket_id.encode()).hexdigest(), 16)
    return (digest % (48 * 60)) / 60.0  # 0–48 hours, in fractional hours


def sla_state(category: str, age_hours: float) -> str:
    target = CATEGORY_STYLE[category]["sla_hours"]
    remaining = target - age_hours
    if remaining <= 0:
        return "⚠️ breached"
    if remaining <= target * 0.25:
        return f"⏳ {remaining:.1f}h left"
    return f"{remaining:.1f}h left"


# --- Override logging ---------------------------------------------------------

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


# --- Views -------------------------------------------------------------------

def render_queue(tickets: List[Dict]) -> Optional[int]:
    """Render the sorted queue table; return the selected row's positional index."""
    rows = []
    for t in tickets:
        cat = t["category"]
        age = simulated_age_hours(t["id"])
        rows.append({
            "Priority": f"{CATEGORY_STYLE[cat]['emoji']} {cat}",
            "Score": t["score"],
            "Subject": t["subject"] or "(no subject)",
            "Suggested queue": t.get("suggested_queue", ""),
            "SLA": sla_state(cat, age),
            "Safety net": "🛡️" if t.get("safety_net_triggered") else "",
        })
    df = pd.DataFrame(rows)

    event = st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Score": st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%d"
            ),
        },
        height=520,
    )
    selected = event.selection.rows
    return selected[0] if selected else None


def render_detail(ticket: Dict) -> None:
    cat = ticket["category"]
    style = CATEGORY_STYLE[cat]
    st.markdown(
        f"<div style='border-left:6px solid {style['color']};padding:0.4rem 0.9rem;'>"
        f"<h3 style='margin:0'>{style['emoji']} {cat} &nbsp;·&nbsp; score {ticket['score']}/100</h3>"
        f"<div style='color:#666'>{ticket['subject'] or '(no subject)'}</div></div>",
        unsafe_allow_html=True,
    )

    if ticket.get("safety_net_triggered"):
        st.warning("🛡️ Critical-class safety net escalated this ticket to at least High.")

    st.markdown("**Why this priority**")
    for bullet in ticket.get("rationale", []) or ["(run the Claude layer for a rationale)"]:
        st.markdown(f"- {bullet}")

    col1, col2 = st.columns(2)
    col1.metric("Suggested queue", ticket.get("suggested_queue") or "—")
    signals = ticket.get("matched_signals") or []
    col2.metric("Signals matched", len(signals))
    if signals:
        col2.caption(", ".join(signals))

    with st.expander("Ticket body"):
        st.write(ticket.get("body") or "(empty)")

    with st.expander("Ground-truth labels (from dataset, for reference)"):
        st.write(f"Priority label: **{ticket.get('true_priority', '—')}**")
        st.write(f"Queue label: **{ticket.get('true_queue', '—')}**")

    render_confirm_adjust(ticket)


def render_confirm_adjust(ticket: Dict) -> None:
    """The 'agent has final say' control — accept or override the category."""
    st.markdown("---")
    st.markdown("**Agent decision** — the system recommends; you decide.")
    cat = ticket["category"]
    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("✅ Confirm", use_container_width=True):
            log_override(ticket["id"], cat, cat, "confirm")
            st.session_state["last_action"] = f"Confirmed {ticket['id']} as {cat}."
    with col2:
        new_cat = st.selectbox(
            "Override category", CATEGORY_ORDER,
            index=CATEGORY_ORDER.index(cat), key=f"ovr_{ticket['id']}",
        )
        if st.button("✏️ Save override", use_container_width=True, disabled=(new_cat == cat)):
            log_override(ticket["id"], cat, new_cat, "override")
            st.session_state["last_action"] = f"Overrode {ticket['id']}: {cat} → {new_cat}."

    if st.session_state.get("last_action"):
        st.success(st.session_state["last_action"])


# --- App ---------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Jordan's Ticket Triage", page_icon="🎫", layout="wide")
    st.title("🎫 Jordan's Ticket Triage Assistant")
    st.caption("A pre-sorted support queue: priority, urgency score, and a plain-language why.")

    tickets = load_tickets()
    if not tickets:
        st.error(
            "No classified tickets found. Run `python -m src.batch_classify` "
            "(after `python src/data_prep.py`) to generate them."
        )
        return

    with st.sidebar:
        st.header("Filters")
        chosen = st.multiselect("Priority", CATEGORY_ORDER, default=CATEGORY_ORDER)
        query = st.text_input("Search subject/body")
        only_net = st.checkbox("Only safety-net escalations")
        st.markdown("---")
        st.metric("Tickets in queue", len(tickets))

    filtered = [
        t for t in tickets
        if t["category"] in chosen
        and (not only_net or t.get("safety_net_triggered"))
        and (not query or query.lower() in (t["subject"] + " " + t["body"]).lower())
    ]

    counts = {c: sum(1 for t in filtered if t["category"] == c) for c in CATEGORY_ORDER}
    cols = st.columns(4)
    for col, c in zip(cols, CATEGORY_ORDER):
        col.metric(f"{CATEGORY_STYLE[c]['emoji']} {c}", counts[c])

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Queue")
        selected_idx = render_queue(filtered)
    with right:
        st.subheader("Ticket detail")
        if selected_idx is not None and selected_idx < len(filtered):
            render_detail(filtered[selected_idx])
        else:
            st.info("Select a ticket in the queue to see its rationale and act on it.")


if __name__ == "__main__":
    main()
