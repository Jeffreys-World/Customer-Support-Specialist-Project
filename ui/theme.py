"""Design tokens and stylesheet injection for the triage console.

Two jobs:

1. **Tokens** — one place that decides what "Critical" looks like. Previously the
   colour/emoji/SLA map lived as a literal dict in ``app.py`` while
   :class:`src.schema.Category` carried a *second* emoji map. They could drift.
   Here the tokens key off ``Category`` directly, so the enum stays the single
   source of truth for what a priority *is* and this module only decides how it
   *looks*.

2. **CSS injection** — Streamlit's theme API can set page colours and little
   else. The dark navigation rail, card surfaces, pills, and the type scale need
   real CSS. :func:`inject_css` loads ``.streamlit/styles.css`` once per session.

Palette values are Zendesk Garden's published tokens, so the console reads as a
peer of the product it is modelled on rather than an approximation of it.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Union

import streamlit as st

from src.schema import Category

REPO_ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = REPO_ROOT / ".streamlit" / "styles.css"
LOGO_PATH = REPO_ROOT / "docs" / "assets" / "logo.svg"
LOGO_MARK_PATH = REPO_ROOT / "docs" / "assets" / "logo-mark.svg"


# --- Palette ------------------------------------------------------------------

class Color:
    """Garden-derived palette. Mirrored in ``styles.css`` as CSS custom properties."""

    RAIL = "#03363D"          # dark teal navigation rail
    RAIL_DEEP = "#02272C"     # rail gradient foot
    RAIL_TEXT = "#E9F0F1"
    RAIL_MUTED = "#8FA9AD"

    PRIMARY = "#1F73B7"       # actions, focus, selection
    PRIMARY_SOFT = "#E7F1FA"

    SURFACE = "#FFFFFF"
    CANVAS = "#F5F7F9"
    BORDER = "#E4E9ED"
    BORDER_STRONG = "#D8DCDE"

    TEXT = "#2F3941"
    TEXT_MUTED = "#68737D"

    CRITICAL = "#CC3340"
    HIGH = "#ED8F1C"
    MEDIUM = "#EFC02D"
    LOW = "#2E8B57"


@dataclass(frozen=True)
class PriorityToken:
    """How one priority level *looks*.

    Deliberately no SLA target here — that's policy, not presentation, and lives
    in :data:`ui.domain.SLA_HOURS` so the countdown logic stays testable without
    importing a stylesheet.
    """

    label: str
    emoji: str
    color: str  # solid accent — left borders, dots, bar fills
    tint: str   # soft background for pills and chips


PRIORITY: Dict[Category, PriorityToken] = {
    Category.CRITICAL: PriorityToken("Critical", Category.CRITICAL.emoji, Color.CRITICAL, "#FCEDEE"),
    Category.HIGH: PriorityToken("High", Category.HIGH.emoji, Color.HIGH, "#FDF3E6"),
    Category.MEDIUM: PriorityToken("Medium", Category.MEDIUM.emoji, Color.MEDIUM, "#FDF8E6"),
    Category.LOW: PriorityToken("Low", Category.LOW.emoji, Color.LOW, "#EAF4EE"),
}

# Most urgent first — the order the queue, KPI row, and filters all present.
CATEGORY_ORDER = [Category.CRITICAL, Category.HIGH, Category.MEDIUM, Category.LOW]
CATEGORY_NAMES = [c.value for c in CATEGORY_ORDER]


def priority(category: Union[Category, str]) -> PriorityToken:
    """Look up tokens by ``Category`` or by its string value.

    Ticket records arrive from JSON with ``category`` as a plain string, so both
    spellings show up across the codebase. Accepting either keeps call sites free
    of defensive conversion.
    """
    if isinstance(category, str):
        category = Category(category)
    return PRIORITY[category]


# --- Stylesheet ---------------------------------------------------------------

def inject_css() -> None:
    """Inject ``.streamlit/styles.css`` into the page.

    Called once per rerun from the entry point, before any view renders — the
    rail and card styling must land before content paints or the first frame
    flashes unstyled.

    Uses ``st.markdown(unsafe_allow_html=True)`` rather than ``st.html``: the
    latter runs its input through a sanitiser that drops ``<style>`` elements
    entirely, so the stylesheet silently never arrives. Verified against 1.39.1 —
    ``st.html`` rendered every component div but zero style rules survived.
    ``st.html`` is still the right tool for the components themselves, which
    contain no ``<style>``.
    """
    if not CSS_PATH.exists():  # degrade to Streamlit defaults rather than crash
        return
    st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def logo_data_uri(path: Path) -> str:
    """Inline an SVG as a data URI for ``st.logo``.

    ``st.logo`` takes a path, but Streamlit's media manager doesn't serve local
    SVG files — it renders a broken image. A data URI sidesteps the media
    endpoint entirely and keeps the SVG as the single source of truth for the
    mark, with no raster copy to regenerate.
    """
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"
