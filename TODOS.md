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

**Status update (2026-08-01, `/plan-ceo-review`):** being addressed, but not as a pixel
diff. A committed PNG baseline was rejected on the same grounds `ui/components.py:574-580`
rejected the KPI emoji — this repo is worked from Windows and macOS, font rasterization
differs between them, and there is no CI to pin a single generator. The version now in
scope asserts computed styles and element presence instead: that `.st-key-*` scoping
resolved, that `.tc-kpi__value` is not Streamlit's default colour, that the rail width
tracks the font-scale token, and that dark mode declares `color-scheme: dark`. Screenshots
are still written for human review; they are just not the pass/fail signal. That catches
the silent degradation this entry was written about without inheriting a cross-machine
trap. Close this entry once those assertions land.

## URL-mirrored view state for attention limit and default sort

**What:** Mirror `pref_attention_limit` and `pref_default_sort` into the query string the
way `ui/theme.py:162-172` already mirrors dark mode, so a pasted link reproduces the exact
view.

**Why:** Surfaced by `/plan-ceo-review` on 2026-08-01 as expansion E4 while building the
preferences substrate. Once all four preferences sit on one persistence layer, adding the
URL mirror to the remaining two is close to free.

**Pros:** A README or portfolio link could open the console at a chosen list length and
sort, not just a chosen theme.

**Cons:** It reverses a decision the code already argues for in `ui/views/settings.py:160-165`:
*"these are not [mirrored], since a shared link carrying someone else's list length would be
surprising rather than useful."* That reasoning still holds. "The substrate makes it cheap"
is not a good enough reason to overturn it.

**Context:** Deferred deliberately, not overlooked. Font size ships mirrored as part of the
same substrate work, because a text-size preference that resets on refresh is an
accessibility defect rather than a preference — that is the same argument that made dark
mode mirrored. The other two are ordinary view state and stay session-scoped. Revisit only
if the console starts publishing shareable deep links.

**Effort estimate:** S (human) → S (with CC). **Priority:** P3.

**Depends on / blocked by:** `ui/prefs.py` lands first (it is the substrate this would
build on).

## Split .streamlit/styles.css into three files

**What:** Break the 1034-line stylesheet into `tokens.css` (custom properties),
`streamlit-shell.css` (the `data-testid` overrides), and `components.css` (our own `tc-*`
classes).

**Why:** Surfaced by `/plan-ceo-review` on 2026-08-01. Nineteen commits touched this one
file in the preceding 30 days. It holds three concerns with completely different risk
profiles: the tokens essentially never break, while the block at line 116 is self-labelled
*"the upgrade-sensitive block"* and is the only part a Streamlit version bump can break.
Burying the fragile third in the same file as the stable two makes it impossible to review
the risky changes on their own.

**Pros:** A Streamlit upgrade becomes a diff against one file instead of a scan of 1034
lines. Token changes stop touching the same file as shell hacks.

**Cons:** Three `read_text` calls instead of one in `inject_css` (mitigated once that
function is cached). A split has no behavioural signature, so it is invisible in review
and easy to get subtly wrong.

**Context:** The UI clarity plan (2026-08-01) adds a type-scale layer and a rail-width
token to this file, which is what pushed it over the line. Do the split *after* that plan
lands, and specifically after the computed-style assertions from the visual-regression
entry above are in place — splitting a stylesheet with nothing asserting how it renders is
the change most likely to break styling silently.

**Effort estimate:** M (human) → S (with CC). **Priority:** P2.

**Depends on / blocked by:** The UI clarity plan ships first; the computed-style assertions
ship before the split.

## Dashboard: a stacked chart is rendering from an empty dataset

**What:** Vega logs `Infinite extent for field "Tickets_end": [Infinity, -Infinity]`
(and `Tickets_start`, `Tickets`) on every Dashboard load. Identify which stacked
chart is receiving zero rows and either stop rendering it or say why it is empty.

**Why:** Surfaced by `/qa` on 2026-08-01 during the post-fix verification sweep.
`[Infinity, -Infinity]` is Vega's empty-domain sentinel: it computes a range from
no data. `_start`/`_end` are the fields Vega generates when it *stacks* a
quantitative field.

**Correction (2026-08-01, second `/qa` pass):** the original hypothesis in this
entry — "a chart is being handed zero rows" — was checked and is **wrong**. Both
stacked charts on the page are the donuts in `_donut`, and both are guarded:
`if channel:` at `ui/views/dashboard.py:284` and `if status["counts"]:` at
`:303`, each falling through to an empty state. The underlying data is fully
populated: 8,469 non-empty values and 4 distinct for `channel`, 8,469 and 3 for
`status`. Neither donut can be rendering from an empty frame.

That leaves two candidates nobody has tested: the grouped bar at `:261`, which
sets `xOffset` to sit bars side by side but may still emit stack fields, and the
legend-click filter added by `_interactive`, which can narrow a selection to
nothing at runtime. Start there rather than re-checking the donuts.

**Pros:** Either a chart disappears that was never showing anything, or a filter
bug surfaces that is currently silent. Both are better than the present state,
where the page looks fine and the console disagrees.

**Cons:** Warning-level only. Nothing visibly breaks, and no user has complained —
this is the console telling on the app rather than a reported symptom.

**Context:** Not caused by the 2026-08-01 QA fixes, which touched `styles.css`,
`styles-dark.css`, and `ui/views/tickets.py` — no chart code. Start at
`ui/views/dashboard.py` and look for a chart whose `_has_data` guard passes but
whose grouped frame is empty; the dataset has known column-completeness gaps
(see the Data integrity panel), so an empty group is plausible rather than
surprising. Full detail in `.gstack/qa-reports/qa-report-localhost-2026-08-01.md`
under ISSUE-008.

**Effort estimate:** S (human) → S (with CC). **Priority:** P3.

**Depends on / blocked by:** Nothing.
