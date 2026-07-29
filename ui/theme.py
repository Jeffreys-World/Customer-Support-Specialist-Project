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
DARK_CSS_PATH = REPO_ROOT / ".streamlit" / "styles-dark.css"
LOGO_PATH = REPO_ROOT / "docs" / "assets" / "logo.svg"
LOGO_MARK_PATH = REPO_ROOT / "docs" / "assets" / "logo-mark.svg"

# Session-state key backing the Settings dark-mode toggle.
_THEME_KEY = "ui_theme"


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

    Carries each value twice, and the duplication is load-bearing:

    * ``color`` / ``tint`` are literal hex. Altair renders to SVG through a
      Vega-Lite spec, where a ``var(--tc-critical)`` reference means nothing —
      charts need the resolved value.
    * ``var_color`` / ``var_tint`` are ``var(...)`` references. Markup emitted
      into the page uses these so a theme swap re-colours pills and score bars
      without re-rendering, which inline hex could never do.

    Deliberately no SLA target here — that's policy, not presentation, and lives
    in :data:`ui.domain.SLA_HOURS` so the countdown logic stays testable without
    importing a stylesheet.
    """

    label: str
    emoji: str
    color: str      # solid accent, literal — chart scales
    tint: str       # soft background, literal — chart scales
    var_color: str  # solid accent, themed — page markup
    var_tint: str   # soft background, themed — page markup


def _token(category: Category, color: str, tint: str, slug: str) -> PriorityToken:
    return PriorityToken(
        label=category.value,
        emoji=category.emoji,
        color=color,
        tint=tint,
        var_color=f"var(--tc-{slug})",
        var_tint=f"var(--tc-{slug}-tint)",
    )


PRIORITY: Dict[Category, PriorityToken] = {
    Category.CRITICAL: _token(Category.CRITICAL, Color.CRITICAL, "#FCEDEE", "critical"),
    Category.HIGH: _token(Category.HIGH, Color.HIGH, "#FDF3E6", "high"),
    Category.MEDIUM: _token(Category.MEDIUM, Color.MEDIUM, "#FDF8E6", "medium"),
    Category.LOW: _token(Category.LOW, Color.LOW, "#EAF4EE", "low"),
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


# --- Theme state --------------------------------------------------------------

def is_dark() -> bool:
    """Is the console currently in dark mode? Session-scoped."""
    return st.session_state.get(_THEME_KEY, "light") == "dark"


def set_dark(enabled: bool) -> None:
    """Set the theme. Backs the Settings toggle."""
    st.session_state[_THEME_KEY] = "dark" if enabled else "light"


# --- Stylesheet ---------------------------------------------------------------

def inject_css() -> None:
    """Inject the console stylesheet, plus the dark overrides when active.

    Called once per rerun from the entry point, before any view renders — the
    rail and card styling must land before content paints or the first frame
    flashes unstyled.

    Uses ``st.markdown(unsafe_allow_html=True)`` rather than ``st.html``: the
    latter runs its input through a sanitiser that drops ``<style>`` elements
    entirely, so the stylesheet silently never arrives. Verified against 1.39.1 —
    ``st.html`` rendered every component div but zero style rules survived.
    ``st.html`` is still the right tool for the components themselves, which
    contain no ``<style>``.

    ## Why dark mode is a second stylesheet rather than an attribute

    The obvious implementation is ``[data-theme="dark"]`` on the root element,
    toggled by a line of JavaScript. Streamlit does not execute ``<script>`` tags
    passed through ``st.markdown``, and the only sanctioned way to run JS —
    ``components.html`` — renders inside an iframe that cannot reach the parent
    document. Streamlit 1.39 also has no runtime theming API (``st.context.theme``
    landed later), and ``config.toml`` is read once at server start.

    So the swap happens in the cascade instead: ``styles-dark.css`` re-declares
    the same ``:root`` custom properties with dark values and is appended after
    the base sheet, where a later declaration of equal specificity wins. Every
    colour in the console resolves through those properties, so one appended file
    re-themes the whole surface with no JS and no rerun trickery.
    """
    if not CSS_PATH.exists():  # degrade to Streamlit defaults rather than crash
        return
    css = CSS_PATH.read_text(encoding="utf-8")
    if is_dark() and DARK_CSS_PATH.exists():
        css += "\n" + DARK_CSS_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def chart_colors() -> Dict[str, str]:
    """Axis/label/grid colours for Altair, which cannot read CSS variables.

    Vega-Lite specs are serialised to JSON and rendered to SVG by Vega, so a
    ``var(--tc-text)`` in a spec is a literal string, not a reference. Charts
    therefore have to be handed resolved values for whichever theme is active.
    """
    if is_dark():
        return {"text": "#E4E9ED", "muted": "#9AA5B1", "grid": "#2C3742",
                "surface": "#1F2933"}
    return {"text": Color.TEXT, "muted": Color.TEXT_MUTED, "grid": Color.BORDER,
            "surface": Color.SURFACE}


def logo_data_uri(path: Path) -> str:
    """Inline an SVG as a data URI for ``st.logo``.

    ``st.logo`` takes a path, but Streamlit's media manager doesn't serve local
    SVG files — it renders a broken image. A data URI sidesteps the media
    endpoint entirely and keeps the SVG as the single source of truth for the
    mark, with no raster copy to regenerate.
    """
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"
