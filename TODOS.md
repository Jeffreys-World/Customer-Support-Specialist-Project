# TODOs

Design debt surfaced by `/plan-design-review` on 2026-07-23, deferred out of the
UI/UX polish pass (see `~/.gstack/projects/Jeffreys-World-Customer-Support-Specialist-Project/flextop-main-design-20260723-132807.md`).

## Full ARIA audit

**What:** Add an ARIA live region so the post-action toast ("Confirmed as Critical")
is announced to screen readers, plus skip-navigation links.

**Why:** The UI redesign locks a baseline (keyboard-tabbable queue rows, a visible
focus ring, an `aria-label` on the safety-net shield icon) but a screen-reader user
still won't hear the toast when it appears — the "reward moment" identified in the
design review is currently silent to them.

**Pros:** Genuinely more accessible; matters if this project ever gets real users
beyond a portfolio demo.

**Cons:** Extra build time for an audience (hiring managers skimming a portfolio)
unlikely to be using a screen reader — though it's still the right thing to do
eventually.

**Depends on / blocked by:** The card-row queue redesign (Approach B) should ship
first — this builds on that structure.

## Dark mode support

**What:** A parallel dark-mode token set so the app respects OS/browser theme
preference instead of forcing light mode via `.streamlit/config.toml`.

**Why:** Some viewers browse with dark mode on; forcing light overrides their
preference.

**Pros:** More polished, more inclusive of viewer preference.

**Cons:** Doubles the color/contrast-verification work locked in the design review's
Design Tokens section, for a project whose success criteria don't currently require it.

**Depends on / blocked by:** The locked light-mode token set (Design Tokens section
of the design doc) ships first — dark mode would be a parallel set calibrated against it.

## Visual regression coverage for CSS-scoping mechanism

**What:** A lightweight visual check (e.g. a `browse`-binary screenshot compared
against a saved baseline) that catches the queue's ghost-button/card styling silently
degrading if a future Streamlit version changes how `.st-key-*` classes are emitted
or placed in the DOM.

**Why:** Surfaced by `/plan-eng-review` on 2026-07-23 (see the plan's Failure Modes
section) as the one failure mode in the whole redesign that's untested, unhandled, AND
silent — the button stays functionally clickable if this breaks, but the visual
identity this whole project was built around would quietly degrade toward default
Streamlit styling with nothing announcing it.

**Pros:** Closes the last known gap in an otherwise fully-covered plan.

**Cons:** Proper visual-diff infrastructure (Percy/Chromatic-style) is real setup work
disproportionate to a single-page portfolio app; even the lightweight version is new
scope beyond the day-or-two UI polish budget.

**Depends on / blocked by:** The redesign (Approach B, all of T1-T8) ships first —
this is a regression-prevention check on the finished visual system, not something to
build alongside it. In the meantime, a manual `/design-review` pass after any future
Streamlit version upgrade is the interim mitigation.
