"""Dashboard — ticket analytics, with the data's own limits stated on the page.

Renamed from "Reporting". The old page was only an embedded copy of
``results/evaluation.md``; this one leads with the queue analytics an agent
actually opens a dashboard to see, and keeps the evaluation report below them.

## Two charts are deliberately missing

The brief asked for average resolution time and ticket volume over time. Neither
is computable from this dataset without inventing numbers:

* **Resolution time** — 49% of closed tickets carry a ``Time to Resolution``
  earlier than their ``First Response Time``. The mean signed duration is about
  -0.06 hours across a uniform ±24h spread, which is noise, not a timeline.
* **Volume over time** — every ``First Response Time`` in the file falls inside a
  single 3-day window. There are three distinct dates in 8,469 rows.

``Date of Purchase`` does span two real years, but it dates the *purchase*, not
the ticket, so plotting it as a ticket trend would be a lie with a real axis.

Both facts are measured live by :func:`ui.domain.data_integrity` and printed in
the integrity panel rather than left in a commit message. A dashboard that
explains why a chart is absent is more trustworthy than one that draws it anyway
— and on this dataset, the absence *is* the finding.

## Why the distributions look flat

Channel, status, type and priority are all close to uniform (~25%/25%/25%/25%).
That is real, and it is shown rather than hidden: the labels in this dataset were
generated independently of the ticket text. The integrity panel carries the
chi-square evidence.

Charts are Altair, which ships with Streamlit — no new dependency. Altair
serialises to a Vega-Lite spec, so it cannot resolve CSS custom properties;
colours come from :func:`ui.theme.chart_colors` and the tokens' literal hex.
"""

from __future__ import annotations

import re
from typing import Optional

import altair as alt
import pandas as pd
import streamlit as st

from src.schema import Category
from ui import components as c
from ui import domain, theme

EVALUATION_REPORT = domain.REPO_ROOT / "results" / "evaluation.md"

# Markdown ATX headings, but not inside a fenced code block.
_HEADING = re.compile(r"^(#{1,5})(\s+\S)", re.MULTILINE)
_FENCE = re.compile(r"^```", re.MULTILINE)

# Most urgent first, matching the queue and the KPI row.
PRIORITY_ORDER = [c_.value for c_ in
                  (Category.CRITICAL, Category.HIGH, Category.MEDIUM, Category.LOW)]
PRIORITY_RANGE = [theme.priority(c_).color for c_ in
                  (Category.CRITICAL, Category.HIGH, Category.MEDIUM, Category.LOW)]


def demote_headings(markdown: str, levels: int = 2) -> str:
    """Push an embedded document's headings below the page's own.

    ``results/evaluation.md`` is a standalone report, so it opens with an h1.
    Rendered as-is inside this page, that h1 came out larger than the page title
    above it and read as the start of a new document rather than a panel within
    this one. Demoting by two levels puts the report's h1 under the page's h1 and
    its section headings under the page's h2. Found by /qa.

    Fenced code blocks are skipped so a ``#`` comment in a shell example is not
    mistaken for a heading.
    """
    out, in_fence = [], False
    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            line = _HEADING.sub(lambda m: "#" * min(len(m.group(1)) + levels, 6) + m.group(2), line)
        out.append(line)
    return "\n".join(out)


# --- Chart helpers ------------------------------------------------------------

def _style(chart: alt.Chart) -> alt.Chart:
    """Apply theme-aware chart chrome.

    Altair cannot read CSS variables (a Vega-Lite spec is JSON, rendered to SVG),
    so every colour has to be resolved in Python for whichever theme is active.

    ``background="transparent"`` is load-bearing for dark mode: Vega-Lite paints
    an opaque white canvas by default, which left every chart sitting on a bright
    slab inside a dark card. It must be paired with ``theme=None`` at the
    ``st.altair_chart`` call site (see :func:`_chart`) — Streamlit's own Vega
    theme is applied *after* the spec and puts the white background back.
    """
    col = theme.chart_colors()
    return (
        chart.configure(background="transparent")
        .configure_view(strokeWidth=0, fill=None)
        .configure_axis(
            labelColor=col["muted"], titleColor=col["muted"],
            gridColor=col["grid"], domainColor=col["grid"],
            tickColor=col["grid"], labelFontSize=11, titleFontSize=11,
        )
        .configure_legend(labelColor=col["muted"], titleColor=col["muted"],
                          labelFontSize=11, titleFontSize=11)
        .configure_title(color=col["text"], fontSize=12)
    )


def _interactive(chart: alt.Chart, legend_field: Optional[str] = None) -> alt.Chart:
    """Add hover-dim and click-a-legend-to-isolate to a chart.

    Vega-Lite resolves both of these in the browser from the chart spec, so this
    is real interaction with no JavaScript of ours and no Streamlit rerun — which
    matters, because a rerun would rebuild the whole page to highlight one bar.
    (``ui.theme.inject_css`` covers why running our own JS is not an option here.)

    The predicate is an **and**, not an or, and that is the whole subtlety. Both
    selections are declared ``empty=True``, meaning "matches everything when
    nothing is selected" — that is what keeps a chart at full opacity on arrival.
    Or-ing them together would leave the idle selection permanently satisfying the
    condition, so every mark would stay fully opaque and the hover would appear to
    do nothing. And-ing gives the intended behaviour in all four states: idle
    (both match, everything opaque), hovering (only that mark), legend filtered
    (only that series), and both at once (the intersection).
    """
    hover = alt.selection_point(on="mouseover", empty=True, clear="mouseout")
    params = [hover]
    predicate = hover

    if legend_field:
        # `bind="legend"` makes the legend itself the control: click an entry to
        # isolate that series, click away to clear. Shift-click adds to it.
        isolate = alt.selection_point(fields=[legend_field], bind="legend", empty=True)
        params.append(isolate)
        predicate = hover & isolate

    return chart.add_params(*params).encode(
        # 0.28 rather than something subtler: at four near-equal categories the
        # dimmed marks have to drop far enough that the highlighted one reads
        # instantly, which is the entire point of the affordance.
        opacity=alt.condition(predicate, alt.value(1.0), alt.value(0.28))
    )


def _chart(chart: alt.Chart) -> None:
    """Render a styled chart.

    ``theme=None`` disables Streamlit's own Vega-Lite theme so the configuration
    from :func:`_style` survives. With the default ``theme="streamlit"`` the
    chart keeps a white background and light axis labels regardless of what the
    spec asks for.
    """
    st.altair_chart(_style(chart), use_container_width=True, theme=None)


def _bar(frame: pd.DataFrame, x: str, y: str, color: str = None,
         x_title: str = "", y_title: str = "", horizontal: bool = False) -> alt.Chart:
    enc = {}
    if horizontal:
        enc["y"] = alt.Y(f"{x}:N", sort="-x", title=x_title)
        enc["x"] = alt.X(f"{y}:Q", title=y_title)
    else:
        enc["x"] = alt.X(f"{x}:N", sort=None, title=x_title)
        enc["y"] = alt.Y(f"{y}:Q", title=y_title)
    if color:
        enc["color"] = color
    chart = alt.Chart(frame).mark_bar(cornerRadius=3).encode(
        tooltip=list(frame.columns), **enc
    )
    return _interactive(chart)


def _donut(frame: pd.DataFrame, category: str, value: str) -> alt.Chart:
    """A donut rather than a pie: the hole makes near-equal slices easier to
    compare by arc length, and this dataset's categories are all near-equal."""
    chart = alt.Chart(frame).mark_arc(innerRadius=55, stroke=None).encode(
        theta=alt.Theta(f"{value}:Q", stack=True),
        color=alt.Color(f"{category}:N", title=None,
                        scale=alt.Scale(scheme="tableau10"),
                        legend=alt.Legend(orient="right")),
        tooltip=[category, value],
    )
    return _interactive(chart, legend_field=category)


def _counts_frame(mapping: dict, key: str, value: str = "Tickets") -> pd.DataFrame:
    return pd.DataFrame({key: list(mapping.keys()), value: list(mapping.values())})


def _has_data(frame: pd.DataFrame, *columns: str) -> bool:
    """True when every named column exists *and* carries at least one value.

    Column presence alone is not enough: ``domain.tickets_frame`` guarantees the
    analytics columns exist so chart code can index them directly, filling them
    with empty strings for a batch generated before the dataset swap. Testing
    ``in frame.columns`` would therefore always pass and hand Altair an empty
    group-by instead of showing the empty state.
    """
    if frame.empty:
        return False
    for column in columns:
        if column not in frame.columns:
            return False
        if not (frame[column].fillna("").astype(str).str.strip() != "").any():
            return False
    return True


# --- Sections -----------------------------------------------------------------

def _kpis(tickets, counts) -> None:
    status = domain.status_summary()
    csat = domain.csat_summary()

    mean = csat["mean"]
    csat_value = f"{mean} / 5" if mean is not None else "—"
    csat_sub = (f"{csat['rated']:,} rated · {csat['coverage'] * 100:.0f}% coverage"
                if csat["rated"] else "no ratings in this batch")

    c.kpi_row([
        ("Open tickets", f"{status['counts'].get('Open', 0):,}",
         f"of {status['total']:,} total", "var(--tc-primary)"),
        ("Awaiting customer", f"{status['counts'].get('Pending Customer Response', 0):,}",
         "pending response", "var(--tc-high)"),
        ("Unresolved rate", f"{status['unresolved_rate'] * 100:.1f}%",
         f"{status['closed']:,} closed", "var(--tc-critical)"),
        ("Satisfaction", csat_value, csat_sub, "var(--tc-low)"),
        ("Critical (AI)", f"{counts.get('Critical', 0):,}",
         "scorer's top band", "var(--tc-critical)"),
    ])
    st.caption(
        "Average resolution time is not shown. This dataset's timestamps cannot "
        "support it — see Data integrity below. Unresolved rate is the honest "
        "substitute: it comes from a status column that is fully populated."
    )


def _volume_charts(frame: pd.DataFrame) -> None:
    left, right = st.columns([3, 2], gap="medium")

    with left:
        c.section("Ticket volume by type and priority")
        if _has_data(frame, "ticket_type", "true_priority"):
            grouped = (
                frame.groupby(["ticket_type", "true_priority"])
                .size().reset_index(name="Tickets")
                .rename(columns={"ticket_type": "Type", "true_priority": "Priority"})
            )
            # The axis labels are raw dataset values ("Refund request"), so they
            # need the same display casing the tags and titles get. Applied to
            # the frame rather than the encoding because Vega renders the literal
            # string it is handed. See `c.humanize` (ISSUE-005).
            grouped["Type"] = grouped["Type"].map(c.humanize)
            chart = _interactive(
                alt.Chart(grouped).mark_bar(cornerRadius=2).encode(
                    x=alt.X("Type:N", title=None, axis=alt.Axis(labelAngle=-25)),
                    y=alt.Y("Tickets:Q", title="Tickets"),
                    color=alt.Color("Priority:N", title="Priority",
                                    scale=alt.Scale(domain=PRIORITY_ORDER, range=PRIORITY_RANGE),
                                    sort=PRIORITY_ORDER),
                    xOffset=alt.XOffset("Priority:N", sort=PRIORITY_ORDER),
                    tooltip=["Type", "Priority", "Tickets"],
                ),
                legend_field="Priority",
            ).properties(height=280)
            _chart(chart)
            st.caption(
                "Grouped by the dataset's own priority label. The bars are near "
                "level across every type — that flatness is the dataset, not the "
                "product mix."
            )
        else:
            c.empty_state("No ticket type data in this batch.")

    with right:
        c.section("Arrival channel")
        channel = domain.count_by("channel")
        if channel:
            _chart(_donut(_counts_frame(channel, "Channel"), "Channel", "Tickets")
                   .properties(height=280))
            top = max(channel.values()) / sum(channel.values()) * 100
            st.caption(
                f"Four channels, largest at {top:.0f}%. An even split is what this "
                "dataset contains, not a rendering fault."
            )
        else:
            c.empty_state("No channel data in this batch.")


def _status_and_satisfaction(frame: pd.DataFrame) -> None:
    left, right = st.columns([2, 3], gap="medium")

    with left:
        c.section("Resolution status")
        status = domain.status_summary()
        if status["counts"]:
            _chart(_donut(_counts_frame(status["counts"], "Status"), "Status", "Tickets")
                   .properties(height=260))
            st.caption(
                f"{status['unresolved']:,} of {status['total']:,} tickets are still "
                "open or awaiting a customer reply."
            )
        else:
            c.empty_state("No status data in this batch.")

    with right:
        c.section("Customer satisfaction")
        csat = domain.csat_summary()
        if csat["histogram"]:
            hist = _counts_frame(
                {f"{k} ★": v for k, v in csat["histogram"].items()}, "Rating"
            )
            chart = _bar(hist, "Rating", "Tickets", y_title="Tickets").encode(
                # labelAngle=0: the default rotates short labels like "3 ★"
                # vertically, which is unreadable for a five-bar histogram.
                x=alt.X("Rating:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
                color=alt.value(theme.priority(Category.LOW).color),
            ).properties(height=260)
            _chart(chart)
            st.caption(
                f"Only closed tickets carry a rating: {csat['rated']:,} of "
                f"{csat['total']:,} ({csat['coverage'] * 100:.1f}%). The mean of "
                f"{csat['mean']} sits at the exact centre of a 1–5 scale, and the "
                "five bars are near-equal — consistent with ratings assigned "
                "independently of anything else in the record."
            )
        else:
            c.empty_state("No satisfaction ratings in this batch.")


def _breakdowns(frame: pd.DataFrame) -> None:
    left, right = st.columns([1, 1], gap="medium")

    with left:
        c.section("Top products by ticket volume")
        products = domain.count_by("product")
        if products:
            top = dict(list(products.items())[:10])
            chart = _bar(_counts_frame(top, "Product"), "Product", "Tickets",
                         horizontal=True, y_title="Tickets").encode(
                color=alt.value(theme.priority(Category.MEDIUM).color)
            ).properties(height=300)
            _chart(chart)
            st.caption(f"Top 10 of {len(products)} products in the batch.")
        else:
            c.empty_state("No product data in this batch.")

    with right:
        c.section("Priority against status")
        if _has_data(frame, "true_priority", "status"):
            grid = (
                frame.groupby(["true_priority", "status"])
                .size().reset_index(name="Tickets")
                .rename(columns={"true_priority": "Priority", "status": "Status"})
            )
            chart = alt.Chart(grid).mark_rect().encode(
                x=alt.X("Status:N", title=None, axis=alt.Axis(labelAngle=-20)),
                y=alt.Y("Priority:N", title=None, sort=PRIORITY_ORDER),
                color=alt.Color("Tickets:Q", scale=alt.Scale(scheme="blues"),
                                legend=alt.Legend(title="Tickets")),
                tooltip=["Priority", "Status", "Tickets"],
            ).properties(height=300)
            _chart(chart)
            st.caption(
                "A uniform block. If priority drove handling, Critical tickets "
                "would close at a different rate than Low ones. They do not."
            )
        else:
            c.empty_state("No status data in this batch.")


def _integrity_panel() -> None:
    c.section("Data integrity")
    facts = domain.data_integrity()
    si = facts.get("subject_independence")

    parts = [
        '<div class="tc-integrity">',
        '<div class="tc-integrity__head">What this data cannot tell you</div>',
    ]

    if si:
        parts.append(
            "<p><strong>The priority label is independent of the ticket text.</strong> "
            f"Chi-square of the ticket subject against its priority label: "
            f"<code>chi2 = {si['chi2']:.1f}</code> on <code>{si['dof']} dof</code>, "
            f"Cramér's V = <code>{si['cramers_v']:.3f}</code>. A chi-square at or below "
            "its degrees of freedom is what independence looks like, and V near zero "
            "means no relationship at all. Every accuracy figure in the evaluation "
            f"below is bounded by this. Only <code>{facts.get('unique_subjects', 0)}</code> "
            "distinct subject lines exist across the batch.</p>"
        )

    pairs = facts.get("timestamp_pairs", 0)
    if pairs:
        parts.append(
            "<p><strong>The timestamps do not describe a timeline.</strong> "
            f"<code>{facts['timestamp_inverted']:,}</code> of "
            f"<code>{pairs:,}</code> closed tickets "
            f"({facts['timestamp_inverted_rate'] * 100:.1f}%) record a resolution "
            "<em>earlier</em> than their first response, and every response "
            f"timestamp falls within <code>{facts.get('response_days', 0)}</code> "
            "distinct days. Average resolution time and ticket-volume-over-time "
            "are therefore not shown anywhere in this console — they were cut "
            "rather than faked.</p>"
        )

    notes = facts.get("resolution_notes", 0)
    if notes:
        parts.append(
            "<p><strong>The resolution notes are generator filler.</strong> "
            f"All <code>{notes:,}</code> closed tickets carry a note and "
            f"<code>{facts.get('resolution_unique', 0):,}</code> of them are unique, but only "
            f"<code>{facts.get('resolution_domain_terms', 0):,}</code> use any support "
            "vocabulary at all (refund, account, replace, reset, …) and "
            f"<code>{facts.get('resolution_mentions_product', 0):,}</code> mention the product "
            "they supposedly fixed. They read like <em>“Case maybe show recently my "
            "computer follow.”</em> The column is carried through the pipeline so it can be "
            "measured here, but the ticket workspace shows resolution <em>state</em> rather "
            "than printing this as an agent's closing note.</p>"
        )

    completeness = domain.field_completeness()
    if completeness:
        explained = [item for item in completeness if item["explained_by_status"]]
        rows = "".join(
            f"<li><code>{c.esc(item['field'])}</code> — "
            f"{item['filled']:,}/{item['total']:,} populated ({item['coverage'] * 100:.1f}%), "
            f"present exactly when status is {c.esc(' or '.join(item['populating_status']))}"
            + ("" if item["explained_by_status"]
               else f" <em>({item['mismatches']:,} exceptions)</em>")
            + "</li>"
            for item in completeness
        )
        parts.append(
            "<p><strong>Every blank field is explained by <code>status</code> alone.</strong>"
            f"<ul>{rows}</ul>"
            f"{len(explained)} of {len(completeness)} fields match their status rule with zero "
            "exceptions. So a “missing first response” flag would fire on exactly the Open "
            "tickets and nothing else — it would rename a column, not add a signal. This also "
            "rules out any <em>days open</em> or <em>overdue</em> metric: the dataset carries no "
            "ticket-creation timestamp, only a purchase date that precedes every ticket by "
            "years. The queue's SLA clock is a hash-derived demo age and says so.</p>"
        )

    csat = facts.get("csat") or {}
    if csat.get("total"):
        parts.append(
            "<p><strong>Satisfaction covers a minority of the queue.</strong> "
            f"<code>{csat['rated']:,}</code> of <code>{csat['total']:,}</code> tickets "
            f"({csat['coverage'] * 100:.1f}%) carry a rating, because only closed "
            "tickets have one. The average above is reported with that coverage "
            "attached wherever it appears.</p>"
        )

    parts.append(
        "<p>None of this is a defect in the console. It is what the source data "
        "supports, measured live from the loaded batch on every render rather "
        "than transcribed from a one-off analysis.</p></div>"
    )
    st.html("".join(parts))


# --- Entry point --------------------------------------------------------------

def render() -> None:
    tickets = domain.load_tickets()
    counts = domain.category_counts(tickets)

    c.app_bar(
        "Dashboard",
        "Queue composition, ticket analytics, and what this data can support.",
        chip=f"{len(tickets):,} tickets classified",
    )

    if not tickets:
        c.empty_state("No classified tickets loaded. Run `python -m src.batch_classify`.")
        return

    frame = domain.tickets_frame()

    _kpis(tickets, counts)
    st.html("<div style='height:.7rem'></div>")

    c.section("Queue composition — the scorer's own priority calls")
    c.priority_bar(counts)
    st.caption(
        "The AI scorer's output distribution across the loaded batch. Source: "
        f"`{domain.active_data_source().name if domain.active_data_source() else 'none'}`. "
        "How these four bands are assigned — the keyword weights, the score "
        "thresholds, and the Critical-class safety net that can override them — is "
        "explained on **Safety-net escalations**. Hover any chart below to isolate a "
        "series; click a legend entry to filter to it."
    )
    st.html("<div style='height:.7rem'></div>")

    _volume_charts(frame)
    st.html("<div style='height:.7rem'></div>")

    _status_and_satisfaction(frame)
    st.html("<div style='height:.7rem'></div>")

    _breakdowns(frame)
    st.html("<div style='height:.7rem'></div>")

    _integrity_panel()
    st.html("<div style='height:.9rem'></div>")

    c.section("Model evaluation")
    if EVALUATION_REPORT.exists():
        with st.expander("Full evaluation report — scorer vs. dataset labels", expanded=False):
            st.markdown(demote_headings(EVALUATION_REPORT.read_text(encoding="utf-8")))
        st.caption(
            f"Rendered from `results/{EVALUATION_REPORT.name}` rather than restated, "
            "so this page can never drift from the committed report. Regenerate "
            "with `python -m src.evaluate`."
        )
    else:
        c.empty_state(
            "No evaluation report found. Run `python -m src.evaluate` to generate "
            "results/evaluation.md."
        )
