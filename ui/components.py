"""Reusable render pieces for the triage console.

Everything here emits markup carrying our own ``tc-*`` classes (styled in
``.streamlit/styles.css``) rather than leaning on Streamlit's internal DOM. That
is the whole point of the split: a Streamlit upgrade can move its own testids
around without touching a single component below.

All dataset-derived text passes through :func:`html.escape` before it reaches
raw HTML — ticket subjects and bodies are arbitrary strings and several contain
angle brackets and ampersands.
"""

from __future__ import annotations

import base64
import html
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import streamlit as st

from src.schema import Category
from ui import demo_context
from ui.domain import simulated_age_hours, sla_state
from ui.theme import Color, priority


def esc(value: object) -> str:
    """Escape untrusted/dataset text for inclusion in raw HTML."""
    return html.escape(str(value if value is not None else ""))


# --- Atoms --------------------------------------------------------------------

def avatar_html(initials: str, color: str, cls: str = "tc-row__avatar") -> str:
    return f'<div class="{cls}" style="background:{esc(color)}">{esc(initials)}</div>'


def avatar_data_uri(initials: str, color: str) -> str:
    """An initials avatar as an SVG data URI, for ``st.chat_message(avatar=...)``.

    ``st.chat_message`` only accepts an emoji or an image, not markup, so the
    thread would otherwise fall back to Streamlit's generic user/assistant glyph
    and break the visual link between a queue row and its conversation.
    """
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40' width='40' height='40'>"
        f"<rect width='40' height='40' rx='20' fill='{color}'/>"
        "<text x='20' y='25' text-anchor='middle' font-family='sans-serif' "
        f"font-size='15' font-weight='700' fill='#ffffff'>{html.escape(initials)}</text></svg>"
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def priority_pill_html(category: str) -> str:
    tok = priority(category)
    return (
        f'<span class="tc-pill" style="background:{tok.tint};color:{tok.color}">'
        f'<span class="tc-pill__dot"></span>{esc(tok.label)}</span>'
    )


def status_pill_html(text: str = "Open") -> str:
    return f'<span class="tc-pill tc-pill--open"><span class="tc-pill__dot"></span>{esc(text)}</span>'


def demo_badge_html(label: str = "simulated") -> str:
    """The D1 marker. Every panel fed by `ui.demo_context` carries one."""
    return f'<span class="tc-pill tc-pill--demo">{esc(label)}</span>'


def score_bar_html(score: int, color: str) -> str:
    pct = max(0, min(100, int(score)))
    return (
        f'<span class="tc-score"><span class="tc-score__track">'
        f'<span class="tc-score__fill" style="width:{pct}%;background:{color}"></span>'
        f'</span>{pct}</span>'
    )


def tags_html(tags: Sequence[str], limit: int = 3) -> str:
    shown = [t for t in tags if t][:limit]
    out = "".join(f'<span class="tc-tag">{esc(t)}</span>' for t in shown)
    extra = len(tags) - len(shown)
    if extra > 0:
        out += f'<span class="tc-tag">+{extra}</span>'
    return out


def section(title: str) -> None:
    """A list/section heading.

    Real <h2>, not a styled div. Replacing Streamlit's st.subheader with custom
    markup removed every heading element from the page, leaving screen-reader
    users with no structure to navigate by (/qa measured h1:0 h2:0). The class
    carries the styling; the tag carries the semantics.
    """
    st.html(f'<h2 class="tc-section">{esc(title)}</h2>')


def empty_state(message: str) -> None:
    st.html(f'<div class="tc-empty">{esc(message)}</div>')


# --- App bar ------------------------------------------------------------------

def app_bar(title: str, subtitle: str, chip: Optional[str] = None, agent_initials: str = "JR") -> None:
    """Top strip: product context on the left, live count and agent on the right.

    Mirrors the reference's top bar (search, "Conversations (8)", avatar) without
    inventing controls that do nothing.
    """
    chip_html = f'<span class="tc-chip">{esc(chip)}</span>' if chip else ""
    st.html(
        '<div class="tc-appbar">'
        # <h1>, not <p>: this is the page title, and it was the missing top of
        # the heading outline (/qa, ISSUE-006).
        f'<div><h1 class="tc-appbar__title">{esc(title)}</h1>'
        f'<p class="tc-appbar__sub">{esc(subtitle)}</p></div>'
        '<div class="tc-appbar__spacer"></div>'
        f"{chip_html}"
        f'<div class="tc-appbar__avatar" aria-hidden="true">{esc(agent_initials)}</div>'
        "</div>"
    )


# --- Ticket row ---------------------------------------------------------------

def ticket_row(ticket: Dict, key: str, open_label: str = "Open") -> bool:
    """One conversation row. Returns True when the agent opens it.

    Rendered as markup rather than a dataframe cell because the reference row is
    an avatar, a two-line block, and a chip cluster — a table cell can't hold
    that. The explicit Open button is a deliberate departure from Zendesk's
    fully-clickable row: Streamlit has no click target for arbitrary HTML, and a
    visible affordance also answers the "hard to navigate" complaint directly.
    """
    tok = priority(ticket["category"])
    req = demo_context.requester_for(ticket)
    age = simulated_age_hours(ticket["id"])
    sla = sla_state(ticket["category"], age)

    with st.container(border=True):
        left, right = st.columns([12, 2], vertical_alignment="center")
        with left:
            st.html(
                '<div class="tc-row">'
                + avatar_html(req.initials, req.avatar_color)
                + '<div class="tc-row__body">'
                + '<div class="tc-row__top">'
                + f'<span class="tc-row__name">{esc(req.name)}</span>'
                + f'<span class="tc-row__sep">|</span>'
                + f'<span class="tc-row__subject">{esc(ticket.get("subject") or "(no subject)")}</span>'
                + "</div>"
                + '<div class="tc-row__meta">'
                + priority_pill_html(ticket["category"])
                + status_pill_html()
                + score_bar_html(ticket.get("score", 0), tok.color)
                + f'<span class="tc-row__sep">·</span><span>{esc(sla)}</span>'
                + f'<span class="tc-row__sep">·</span><span>{esc(demo_context._ago(age))}</span>'
                + f'<span class="tc-row__sep">·</span><span>#{esc(ticket["id"])}</span>'
                + ("<span class='tc-row__sep'>·</span><span>🛡️ safety net</span>"
                   if ticket.get("safety_net_triggered") else "")
                + "</div>"
                + f'<div class="tc-row__meta">{tags_html(ticket.get("tags") or [])}</div>'
                + "</div></div>"
            )
        with right:
            return st.button(open_label, key=key, use_container_width=True)


# --- Statistics rail ----------------------------------------------------------

def stat_block(head: str, period: str, items: Iterable[Tuple[str, object, str]]) -> None:
    """A statistics card: heading, period caption, then value/label pairs.

    ``items`` is (label, value, colour). Mirrors the reference's "Ticket
    statistics / This week" and "Satisfaction statistics / 60 days" cards.
    """
    cells = "".join(
        f'<div><div class="tc-stat__value" style="color:{esc(color)}">{esc(value)}</div>'
        f'<div class="tc-stat__label">{esc(label)}</div></div>'
        for label, value, color in items
    )
    st.html(
        f'<div class="tc-stat"><div class="tc-stat__head">{esc(head)}</div>'
        f'<div class="tc-stat__period">{esc(period)}</div>'
        f'<div class="tc-stat__grid">{cells}</div></div>'
    )


# --- Detail-view panels -------------------------------------------------------

def panel_title(text: str, badge: bool = False) -> None:
    """Panel heading — <h3>, one level below the section headings it sits under."""
    suffix = " " + demo_badge_html() if badge else ""
    st.html(f'<h3 class="tc-panel__title">{esc(text)}{suffix}</h3>')


def field(label: str, value: object, value_html: Optional[str] = None) -> None:
    """One label/value pair in a properties or requester panel."""
    rendered = value_html if value_html is not None else esc(value if value not in (None, "") else "—")
    st.html(
        f'<div class="tc-field"><div class="tc-field__label">{esc(label)}</div>'
        f'<div class="tc-field__value">{rendered}</div></div>'
    )


def internal_note(bullets: List[str], head: str = "Internal note · why this priority") -> None:
    """Zendesk's amber internal-note block, carrying the AI rationale.

    This is the one place where the reference layout and our real data line up
    exactly: an internal note is a message visible to agents but not the
    customer, which is precisely what a triage rationale is.
    """
    items = "".join(f"<li>{esc(b)}</li>" for b in bullets) or "<li>No rationale recorded.</li>"
    st.html(f'<div class="tc-note"><div class="tc-note__head">{esc(head)}</div><ul>{items}</ul></div>')


def history_list(items: Iterable[demo_context.HistoryItem]) -> None:
    rows = "".join(
        f'<div class="tc-history__item"><div class="tc-history__title">{esc(i.title)}</div>'
        f'<div class="tc-history__meta">{esc(i.status)} · {esc(i.when)}</div></div>'
        for i in items
    )
    st.html(f"<div>{rows}</div>")


def requester_panel(ticket: Dict) -> None:
    """Right-hand contact card. Entirely simulated — badged accordingly (D1)."""
    req = demo_context.requester_for(ticket)
    panel_title("Requester", badge=True)
    st.html(
        '<div class="tc-row" style="margin-bottom:.6rem">'
        + avatar_html(req.initials, req.avatar_color)
        + f'<div class="tc-row__body"><div class="tc-row__name">{esc(req.name)}</div>'
        + f'<div class="tc-history__meta">{esc(req.org)}</div></div></div>'
    )
    field("Email", req.email)
    field("Phone", req.phone)
    field("Local time", f"{req.local_time()} · {req.city}")
    field("Notes", f"Valued customer since {req.customer_since}")


def filter_row(key_prefix: str, show_queue: bool = True) -> Dict[str, object]:
    """The filter strip above the list.

    Stands in for the reference's Channel / Status / Recommended dropdowns, with
    controls that map to fields this dataset actually has.
    """
    from ui.domain import QUEUE_OPTIONS  # local import avoids a cycle at module load

    widths = [4, 3, 3, 2] if show_queue else [5, 3, 2]
    cols = st.columns(widths, vertical_alignment="bottom")

    query = cols[0].text_input(
        "Search", placeholder="Search subject or body",
        key=f"{key_prefix}_q", label_visibility="collapsed",
    )
    cats = cols[1].multiselect(
        "Priority", [c.value for c in Category], default=None,
        key=f"{key_prefix}_cat", placeholder="Priority",
        label_visibility="collapsed",
    )
    queues: List[str] = []
    if show_queue:
        queues = cols[2].multiselect(
            "Queue", QUEUE_OPTIONS, default=None, key=f"{key_prefix}_queue",
            placeholder="Queue", label_visibility="collapsed",
        )
    sort = cols[-1].selectbox(
        "Sort", ["Recommended", "Oldest first", "Highest score"],
        key=f"{key_prefix}_sort", label_visibility="collapsed",
    )
    return {"query": query, "categories": cats, "queues": queues, "sort": sort}


def priority_bar(counts: Dict[str, int]) -> None:
    """Four-up priority KPI row, always showing all four levels even at zero."""
    cols = st.columns(4)
    for col, cat in zip(cols, [c for c in Category]):
        tok = priority(cat)
        with col:
            st.html(
                f'<div class="tc-stat"><div class="tc-stat__value" style="color:{tok.color}">'
                f'{counts.get(cat.value, 0)}</div>'
                f'<div class="tc-stat__label">{tok.emoji} {esc(tok.label)}</div></div>'
            )
