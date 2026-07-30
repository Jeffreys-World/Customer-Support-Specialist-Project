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
    """A priority pill.

    Uses the token's ``var(...)`` spellings, not its literal hex: inline hex
    would survive a theme swap unchanged and leave every pill wearing light-mode
    colours on a dark card.
    """
    tok = priority(category)
    return (
        f'<span class="tc-pill" style="background:{tok.var_tint};color:{tok.var_color}">'
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
                # The name/subject divider is a CSS border on the subject, not a
                # "|" text node. As a text node it stayed on the name's line when
                # a long subject wrapped, leaving a separator pointing at
                # nothing. Found by /qa.
                + f'<span class="tc-row__subject">{esc(ticket.get("subject") or "(no subject)")}</span>'
                + "</div>"
                + '<div class="tc-row__meta">'
                + priority_pill_html(ticket["category"])
                + status_pill_html()
                + score_bar_html(ticket.get("score", 0), tok.var_color)
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

def count(value: object) -> str:
    """Render a count with thousands separators, passing other values through.

    Formatting lives here rather than at each call site so every statistic in the
    console reads the same way. The queue routinely holds four-figure counts, and
    the rails were rendering a bare "4433" beside the Dashboard's "8,469".
    Non-integers (percentages, pre-formatted strings, em dashes) pass untouched.
    """
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def stat_block(head: str, period: str, items: Iterable[Tuple[str, object, str]]) -> None:
    """A statistics card: heading, period caption, then value/label pairs.

    ``items`` is (label, value, colour). Mirrors the reference's "Ticket
    statistics / This week" and "Satisfaction statistics / 60 days" cards.
    """
    cells = "".join(
        f'<div><div class="tc-stat__value" style="color:{esc(color)}">{esc(count(value))}</div>'
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
    """Right-hand contact card.

    Badging is per-field rather than per-panel since the dataset swap. Name and
    email are real dataset columns now, so stamping the whole panel "simulated"
    would understate what the console actually knows. Phone, organisation, local
    time and tenure have no source column and stay derived — those keep the badge
    (D1).
    """
    req = demo_context.requester_for(ticket)
    panel_title("Requester", badge=not req.identity_is_real)
    st.html(
        '<div class="tc-row" style="margin-bottom:.6rem">'
        + avatar_html(req.initials, req.avatar_color)
        + f'<div class="tc-row__body"><div class="tc-row__name">{esc(req.name)}</div>'
        + f'<div class="tc-history__meta">{esc(req.org)} {demo_badge_html()}</div></div></div>'
    )
    # Name and email are both real dataset columns, but the dataset generated them
    # independently: only 1.0% of the 8,469 rows have an email whose local part
    # relates to the customer's name. So the card legitimately shows
    # "Gregory Bautista / johnstonbeth@example.com", which reads as a rendering
    # bug unless it is called out. Labelled rather than hidden, and rather than
    # substituting a tidy derived address, because the value itself is real —
    # it is the pairing that carries no meaning. Found by /qa (ISSUE-011).
    field("Email", req.email)
    if req.identity_is_real:
        st.caption(
            "Name and email are both real dataset fields, but this dataset pairs "
            "them at random — they are not the same person's details."
        )
    field("Phone", req.phone, value_html=f"{esc(req.phone)} {demo_badge_html()}")
    field("Local time",
          f"{req.local_time()} · {req.city}",
          value_html=f"{esc(req.local_time())} · {esc(req.city)} {demo_badge_html()}")
    field("Notes",
          f"Valued customer since {req.customer_since}",
          value_html=f"Valued customer since {esc(req.customer_since)} {demo_badge_html()}")


def filter_row(key_prefix: str, show_queue: bool = True) -> Dict[str, object]:
    """The filter strip above the list.

    Stands in for the reference's Channel / Status / Recommended dropdowns, with
    controls that map to fields this dataset actually has.
    """
    # Offer only queues the loaded batch actually uses. The full QUEUE_OPTIONS
    # enum is the set the LLM may *suggest*; three of them (Returns and
    # Exchanges, Sales and Pre-Sales, Human Resources) never appear in the data,
    # so listing them gave the agent filters that always returned an empty queue
    # with no explanation. Found by /qa.
    from ui.domain import queues_in_use  # local import avoids a cycle at module load

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
            "Queue", queues_in_use(), default=None, key=f"{key_prefix}_queue",
            placeholder="Queue", label_visibility="collapsed",
        )
    from ui.domain import SORT_OPTIONS
    from ui.state import default_sort

    sort = cols[-1].selectbox(
        "Sort", SORT_OPTIONS,
        index=SORT_OPTIONS.index(default_sort()),
        key=f"{key_prefix}_sort", label_visibility="collapsed",
    )
    return {"query": query, "categories": cats, "queues": queues, "sort": sort}


def kpi_card(label: str, value: object, sub: str = "", color: str = "var(--tc-text)") -> str:
    """One dashboard KPI tile: big number, label, and a qualifying caption.

    ``sub`` is not decoration. Several of these figures are only meaningful with
    their coverage attached (the satisfaction average describes the third of the
    batch that is closed), and the caption is where that qualifier goes so the
    number is never shown bare.
    """
    sub_html = f'<div class="tc-kpi__sub">{esc(sub)}</div>' if sub else ""
    return (
        f'<div class="tc-kpi"><div class="tc-kpi__label">{esc(label)}</div>'
        f'<div class="tc-kpi__value" style="color:{color}">{esc(value)}</div>'
        f"{sub_html}</div>"
    )


def kpi_row(cards: Sequence[Tuple[str, object, str, str]]) -> None:
    """Render KPI tiles across an even grid."""
    cols = st.columns(len(cards))
    for col, (label, value, sub, color) in zip(cols, cards):
        with col:
            with st.container(border=True):
                st.html(kpi_card(label, value, sub, color))


def profile_menu(name: str = "Jordan Rivera", role: str = "Support Specialist",
                 initials: str = "JR") -> None:
    """The rail-foot profile menu: avatar, name, and a quick-access dropdown.

    Built on ``st.popover`` because Streamlit has no native menu widget and the
    reference's profile control is a click-to-open list, not a select box.

    On what these entries do: this is a portfolio console with no auth layer, no
    mail path, and one hard-coded agent. Rather than ship four dead links styled
    to look live, each entry either routes somewhere real (Account settings →
    the Settings page) or says plainly that it is inert. That is the same
    standard `docs/UI_SPEC.md` already holds the composer and the macro button
    to — a control that lies about being wired up is worse than an absent one.
    """
    with st.sidebar:
        st.html('<div class="tc-profile__rule"></div>')
        with st.popover(f"👤  {name}", use_container_width=True):
            st.html(
                '<div class="tc-row" style="margin-bottom:.5rem">'
                + avatar_html(initials, Color.PRIMARY)
                + f'<div class="tc-row__body"><div class="tc-row__name">{esc(name)}</div>'
                + f'<div class="tc-history__meta">{esc(role)}</div></div></div>'
            )
            st.caption("Signed in as the demo agent.")

            if st.button("View profile", key="pm_profile", use_container_width=True):
                st.session_state["_profile_notice"] = (
                    "View profile is not implemented — this console has a single "
                    "hard-coded agent and no user directory behind it."
                )
            if st.button("Account settings", key="pm_settings", use_container_width=True):
                st.switch_page(st.session_state["_page_settings"])
            if st.button("Help & support", key="pm_help", use_container_width=True):
                st.session_state["_profile_notice"] = (
                    "Help & support is not implemented — there is no help centre "
                    "behind this build. The README covers how the console works."
                )
            if st.button("Log out", key="pm_logout", use_container_width=True):
                st.session_state["_profile_notice"] = (
                    "Log out is not implemented — the console has no auth layer, "
                    "so there is no session to end."
                )

            notice = st.session_state.get("_profile_notice")
            if notice:
                st.caption(notice)


def scorer_explainer(
    reference: Dict[str, object],
    stats: Dict[str, object],
    example: Optional[Dict[str, object]] = None,
) -> None:
    """"How priority is decided" — the scoring rules and the Critical-class safety net.

    Takes the rules as data (``ui.domain.scorer_reference``) rather than reaching
    into the scorer itself, so this function only decides how the explanation
    *looks*. Every number below arrives from the scorer's own constants: nothing
    here is a transcribed copy that could disagree with the code.

    Ordered the way a question actually arrives. An agent looking at a queue asks
    "why is this one Critical?", so: the score bands first (what the number
    means), then the keyword weights (where the number comes from), then the
    safety net (the rule that can override the number), then one worked example
    with the arithmetic showing.
    """
    bands: List[Dict] = reference["bands"]          # type: ignore[assignment]
    tiers: List[Dict] = reference["tiers"]          # type: ignore[assignment]

    st.html(
        '<div class="tc-explain">'
        '<p class="tc-explain__lede">Every ticket is scored from its own text before '
        'an agent sees it. No machine learning, no model call: the scorer counts '
        'keyword matches, adds their weights, and the total lands in one of four '
        'bands. The same text always produces the same score, and every point is '
        'traceable to a phrase in the ticket.</p></div>'
    )

    # --- 1. What the number means ---------------------------------------------
    panel_title("1 · The four bands")
    rows = "".join(
        f'<div class="tc-explain__row">'
        f'<span class="tc-explain__range">{band["floor"]}–{band["ceiling"]}</span>'
        f'{priority_pill_html(band["category"])}'
        f'<span class="tc-explain__note">respond within {band["sla_hours"]}h</span>'
        f"</div>"
        for band in bands
    )
    st.html(f'<div class="tc-explain">{rows}</div>')
    st.caption(
        f"Scores run {reference['base']}–{reference['max']}. Every ticket starts at "
        f"**{reference['base']}** — the neutral baseline — so a ticket with no "
        "recognised keyword at all sits in the lowest band rather than at zero."
    )

    # --- 2. Where the number comes from ---------------------------------------
    panel_title("2 · What the keywords are worth")
    tier_rows = []
    for tier in tiers:
        groups: List[Dict] = tier["groups"]  # type: ignore[assignment]
        phrases = sum(int(g["count"]) for g in groups)
        sample = ", ".join(str(g["name"]) for g in groups[:6])
        more = f" +{len(groups) - 6} more" if len(groups) > 6 else ""
        tier_rows.append(
            f'<div class="tc-explain__row">'
            f'<span class="tc-explain__weight">+{tier["weight"]}</span>'
            f'<span class="tc-explain__tier">{esc(tier["label"])}'
            f'<span class="tc-explain__note"> {len(groups)} signal groups, '
            f"{phrases} phrases</span></span>"
            f'<span class="tc-explain__sample">{esc(sample)}{esc(more)}</span>'
            f"</div>"
        )
    repeat = reference["repeat"]
    tier_rows.append(
        f'<div class="tc-explain__row">'
        f'<span class="tc-explain__weight">+{repeat["weight"]}</span>'  # type: ignore[index]
        f'<span class="tc-explain__tier">Repeat contact'
        f'<span class="tc-explain__note"> once only, '
        f'{len(repeat["variants"])} phrases</span></span>'  # type: ignore[index,arg-type]
        f'<span class="tc-explain__sample">"again", "still not", "third time"</span>'
        f"</div>"
    )
    st.html(f'<div class="tc-explain">{"".join(tier_rows)}</div>')
    st.caption(
        "A signal group fires at most once no matter how many of its phrases "
        "appear, so repeating a word cannot inflate a score. Weights are "
        "deliberately coarse: the scale only has to separate four bands, and "
        "finer weights would imply a precision the keyword lists do not have."
    )

    # --- 3. The rule that can override the number ------------------------------
    hard: List[Dict] = reference["hard_triggers"]  # type: ignore[assignment]
    trigger_names = ", ".join(str(g["name"]) for g in hard)
    by_category: Dict[str, int] = stats["by_category"]  # type: ignore[assignment]
    below = sum(
        count for name, count in by_category.items()
        if name not in (Category.CRITICAL.value, Category.HIGH.value)
    )
    st.html(
        '<div class="tc-explain__net">'
        '<div class="tc-explain__net-head">3 · The Critical-class safety net</div>'
        "<p>The costliest failure in triage is not a routine ticket read as urgent. "
        "It is an urgent ticket read as routine, sitting in a queue while the "
        "customer waits. So the score is not the last word.</p>"
        f"<p><strong>Any ticket containing a hard-trigger phrase is forced to at "
        f'least {esc(reference["safety_net_category"])}, whatever it scored.</strong> '
        f'There are {len(hard)} hard-trigger groups: <em>{esc(trigger_names)}</em>. '
        f'A ticket the net catches is lifted to a score of '
        f'{reference["safety_net_floor"]}, the floor of that band.</p>'
        f"<p>This is a guarantee about vocabulary, not a prediction, which is why "
        f"it is stated as a rule rather than an accuracy figure. On the batch "
        f'loaded right now it fired on <code>{stats["fired"]:,}</code> of '
        f'<code>{stats["total"]:,}</code> tickets '
        f'({float(stats["rate"]) * 100:.1f}%), and lifted '
        f'<code>{stats["lifted_to_floor"]:,}</code> of those from below the line. '
        f"Of every ticket it touched, <code>{below}</code> ended up below "
        f'{esc(reference["safety_net_category"])} — the invariant holds, measured '
        f"on every render rather than asserted.</p>"
        "<p>The trade is deliberate and it costs precision: the net over-fires to "
        "High on some routine tickets. A false alarm wastes a minute of an agent's "
        "time. A missed critical ticket costs a customer.</p>"
        "</div>"
    )

    # --- 4. The arithmetic, on one real sentence -------------------------------
    if example:
        panel_title("4 · A worked example")
        lines = "".join(
            f'<div class="tc-explain__row">'
            f'<span class="tc-explain__weight">+{line["weight"]}</span>'
            f'<span class="tc-explain__tier">{esc(line["signal"])}'
            + ('<span class="tc-explain__hard">hard trigger</span>' if line["hard"] else "")
            + "</span></div>"
            for line in example["lines"]  # type: ignore[union-attr]
        )
        outcome = (
            f'keyword mass alone reached {example["raw"]}, which is '
            f'{example["category"]}'
        )
        if example["lifted_by_net"]:
            outcome = (
                f'keyword mass alone reached only <strong>{example["raw"]}</strong>, which '
                f'would have been Medium. The safety net lifted it to '
                f'<strong>{example["score"]}</strong> because "system down" is a hard '
                f"trigger. This is the case the net exists for"
            )
        elif example["clamped"]:
            outcome = (
                f'the weights summed to {example["raw"]}, clamped to the '
                f'{reference["max"]} maximum'
            )
        st.html(
            f'<div class="tc-explain">'
            f'<p class="tc-explain__quote">{esc(example["text"])}</p>'
            f'<div class="tc-explain__row">'
            f'<span class="tc-explain__weight">{example["base"]}</span>'
            f'<span class="tc-explain__tier">starting baseline</span></div>'
            f"{lines}"
            f'<div class="tc-explain__row tc-explain__row--total">'
            f'<span class="tc-explain__weight">{example["score"]}</span>'
            f'<span class="tc-explain__tier">final score</span>'
            f'{priority_pill_html(example["category"])}</div>'
            f'<p class="tc-explain__note">So: {outcome}.</p>'
            f"</div>"
        )


def priority_bar(counts: Dict[str, int]) -> None:
    """Four-up priority KPI row, always showing all four levels even at zero."""
    cols = st.columns(4)
    for col, cat in zip(cols, [c for c in Category]):
        tok = priority(cat)
        with col:
            st.html(
                f'<div class="tc-stat"><div class="tc-stat__value" style="color:{tok.var_color}">'
                f'{esc(count(counts.get(cat.value, 0)))}</div>'
                f'<div class="tc-stat__label">{tok.emoji} {esc(tok.label)}</div></div>'
            )
