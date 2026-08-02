"""The ticket workspace — reference 2.

Three columns, matching Zendesk's agent view: ticket properties on the left, the
conversation in the middle, requester context on the right, with an open-ticket
tab strip above and the composer below.

What is real and what is not:

* **Real** — priority, score, matched signals, safety-net state, suggested queue,
  ground-truth labels, tags, the ticket body, ticket status, resolution state, the
  AI rationale, and the agent's confirm/override decision (which is written to
  ``results/override_log.csv``).
* **Simulated** — requester identity, the agent reply turn, and interaction
  history. Each of those panels is rendered with a "simulated" badge (D1).
* **Withheld** — the dataset's ``Resolution`` note text. The column is carried
  through the pipeline and measured on the Dashboard, but it is generator filler
  ("Case maybe show recently my computer follow."), so this panel shows resolution
  *state* instead of printing prose that would read as a real agent's closing note.
"""

from __future__ import annotations

from typing import Dict, List

import streamlit as st

from src.schema import Category
from ui import components as c
from ui import demo_context, domain, state
from ui.theme import priority


def render(ticket: Dict, tickets: List[Dict]) -> None:
    _tab_strip(tickets)

    tok = priority(ticket["category"])
    req = demo_context.requester_for(ticket)
    c.app_bar(
        c.humanize(ticket.get("subject") or "(no subject)"),
        f"#{ticket['id']} · {req.name} · {req.org}",
        chip=f"{tok.emoji} {tok.label}",
    )

    toast = state.pop_last_action()
    if toast:
        st.success(toast)

    props, convo, context = st.columns([3, 6, 3], gap="medium")
    with props:
        _properties(ticket)
    with convo:
        _conversation(ticket)
        _composer(ticket)
    with context:
        with st.container(border=True):
            c.requester_panel(ticket)
        with st.container(border=True):
            c.panel_title("Interaction history", badge=True)
            c.history_list(demo_context.history_for(ticket))


# --- Tab strip ----------------------------------------------------------------

def _tab_strip(tickets: List[Dict]) -> None:
    """Open tickets as tabs, mirroring the reference's conversation tab row."""
    open_ids = state.open_tabs()
    if not open_ids:
        return

    active = state.active_ticket_id()
    cols = st.columns(len(open_ids) + 3, vertical_alignment="center")

    for col, tid in zip(cols, open_ids):
        item = state.find_ticket(tickets, tid)
        label = f"#{tid}" if item is None else f"{priority(item['category']).emoji} #{tid}"
        with col:
            if st.button(
                label,
                key=f"tab_{tid}",
                use_container_width=True,
                type="primary" if tid == active else "secondary",
            ):
                state.set_active(tid)
                st.rerun()

    with cols[len(open_ids)]:
        if st.button("✕ Close", key="tab_close", use_container_width=True):
            if active:
                state.close_ticket(active)
            st.rerun()
    with cols[len(open_ids) + 1]:
        if st.button("← Queue", key="tab_back", use_container_width=True):
            state.set_active(None)
            st.rerun()


# --- Left column: ticket properties -------------------------------------------

def _properties(ticket: Dict) -> None:
    tok = priority(ticket["category"])
    with st.container(border=True):
        c.panel_title("Ticket properties")
        c.field("Priority (AI)", None, value_html=c.priority_pill_html(ticket["category"]))
        c.field(
            "Urgency score", None,
            value_html=c.score_bar_html(ticket.get("score", 0), tok.color),
        )
        c.field("Suggested queue", ticket.get("suggested_queue") or "—")
        c.field(
            "Safety net", None,
            value_html=(
                "🛡️ Escalated to at least High" if ticket.get("safety_net_triggered")
                else "Not triggered"
            ),
        )
        signals = ticket.get("matched_signals") or []
        c.field(
            "Matched signals", None,
            value_html=c.tags_html(signals, limit=8) if signals else "—",
        )
        c.field("Tags", None, value_html=c.tags_html(ticket.get("tags") or [], limit=8) or "—")
        c.field("Status", c.humanize(ticket.get("status") or "—"))
        c.field("Resolution", domain.resolution_state(ticket))
        st.caption(
            "Resolution shows state, not the dataset's note text — those notes are "
            "generator filler. Measured under Dashboard → Data integrity."
        )

    with st.container(border=True):
        c.panel_title("Dataset labels")
        st.caption("Ground truth, shown for evaluation only. Never used to score.")
        c.field("Priority label", ticket.get("true_priority") or "—")
        c.field("Queue label", ticket.get("true_queue") or "—")


# --- Middle column: conversation ----------------------------------------------

def _conversation(ticket: Dict) -> None:
    c.section("Conversation")
    turns = demo_context.thread_for(ticket)

    req = demo_context.requester_for(ticket)
    for i, turn in enumerate(turns):
        if turn.role == "requester":
            avatar = c.avatar_data_uri(req.initials, req.avatar_color)
        else:
            avatar = c.avatar_data_uri("JR", "#03363D")  # the agent, matching the rail
        with st.chat_message(turn.role, avatar=avatar):
            head = f"**{turn.author}** · {turn.when}"
            if turn.simulated:
                st.html(
                    f'<div class="tc-row__meta"><span class="tc-row__name">{c.esc(turn.author)}</span>'
                    f'<span class="tc-row__sep">·</span><span>{c.esc(turn.when)}</span>'
                    f"{c.demo_badge_html()}</div>"
                )
            else:
                st.markdown(head)
            st.write(turn.body)

        # The rationale sits directly under the customer's message, which is where
        # Zendesk puts an internal note — visible to agents, never to the customer.
        if i == 0:
            c.internal_note(
                ticket.get("rationale") or ["No rationale recorded for this ticket."]
            )


# --- Composer -----------------------------------------------------------------

def _composer(ticket: Dict) -> None:
    """The agent's decision control, shaped like Zendesk's composer footer.

    The reply box is presentational — this project has no outbound mail path —
    but the priority decision beside it is entirely real and is what
    ``results/override_log.csv`` records for the manual spot-check.
    """
    st.html("<div style='height:.5rem'></div>")
    with st.container(border=True):
        st.text_area(
            "Reply", key=f"reply_{ticket['id']}", height=90,
            placeholder="Write a reply to the customer…",
            label_visibility="collapsed",
        )
        st.caption("Replies are not delivered — this console triages, it doesn't send mail.")

        current = ticket["category"]
        left, right = st.columns([3, 2], vertical_alignment="bottom")
        with left:
            new_cat = st.selectbox(
                "Priority",
                [cat.value for cat in Category],
                index=[cat.value for cat in Category].index(current),
                key=f"ovr_{ticket['id']}",
            )
        with right:
            if new_cat == current:
                # "Submit as Open" named a *status*, in the one control on the page
                # that sets a *priority*. It was wrong three ways at once: nothing
                # here writes status, so the claim was never true; the ticket beside
                # it read "Pending Customer Response", so the label contradicted the
                # properties panel; and the override branch below renders "Submit as
                # High", so the same phrase meant two different fields depending on
                # a dropdown. The toast has always said "Confirmed … as Critical" —
                # this makes the button agree with the toast. Found by /qa
                # (ISSUE-103).
                if st.button(f"Confirm as {current}", key=f"confirm_{ticket['id']}",
                             type="primary", use_container_width=True):
                    domain.log_override(ticket["id"], current, current, "confirm")
                    state.set_last_action(f"Confirmed #{ticket['id']} as {current}.")
                    st.rerun()
            else:
                if st.button(f"Submit as {new_cat}", key=f"override_{ticket['id']}",
                             type="primary", use_container_width=True):
                    domain.log_override(ticket["id"], current, new_cat, "override")
                    state.set_last_action(
                        f"Overrode #{ticket['id']}: {current} → {new_cat}."
                    )
                    st.rerun()

        following = state.following()
        is_following = ticket["id"] in following
        if st.button(
            "★ Following" if is_following else "☆ Follow",
            key=f"follow_{ticket['id']}", use_container_width=True,
        ):
            state.toggle_following(ticket["id"])
            st.rerun()
