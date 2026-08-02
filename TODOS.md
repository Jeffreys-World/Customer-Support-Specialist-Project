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

## The navigation rail marks the current page by colour alone

**What:** All seven `stSidebarNavLink` elements report `aria-current: null`, including
the active one. The current destination is conveyed only by a background colour —
`rgba(153,173,194,0.25)` against `rgba(0,0,0,0)`. A screen-reader user gets no
indication of where they are.

**Why:** Surfaced by `/qa` on 2026-08-01 (ISSUE-106). It is also the unaddressed half of
a symptom the ISSUE-003 pass noted — "the rail gave no clue you had arrived somewhere" —
which that fix resolved for sighted users only.

**Why it is not already fixed:** `stSidebarNavLink` is Streamlit's own DOM. Setting an
attribute on it requires JavaScript against the parent document, and `ui/theme.py:184-188`
already documents why this app cannot do that: Streamlit does not execute `<script>` tags
passed through `st.markdown`, and `components.html` renders inside an iframe that cannot
reach the parent. CSS can *style* the active link — that is where the colour comes from —
but cannot add semantics. This is a real constraint, not an oversight.

**Options, both design decisions rather than defect repairs:**

1. A `components.html` bridge reaching out via `window.parent`. Fragile, and the
   sanctioned API deliberately walls this off — it would break on any Streamlit release
   that tightens the sandbox.
2. Render the rail as custom markup instead of `st.navigation`, which would put
   `aria-current` fully under our control but discard the routing the whole app is
   built on.

**Pros:** Closes the last known accessibility gap; it is the standard landmark screen
readers look for.

**Cons:** Neither option is small, and option 1 trades a semantic gap for an upgrade
hazard of exactly the kind `.streamlit/styles.css` line 116 is already labelled for.

**Context:** Pairs naturally with the "Full ARIA audit" entry above — both are rail/shell
semantics, and doing them together is the only way option 2 could be worth its cost.

**Effort estimate:** M (human) → S (with CC). **Priority:** P3.

**Depends on / blocked by:** Nothing technically. Worth deciding alongside the ARIA audit
rather than on its own.

## ~~Dashboard: a stacked chart is rendering from an empty dataset~~ — CLOSED, not a bug

**Closed 2026-08-01 by the third `/qa` pass.** Both earlier diagnoses were wrong, and the
warning is not this project's to fix. Kept rather than deleted because two passes have now
been spent on it and the next reader deserves the evidence.

**What it actually is:** Streamlit ships the dataframe to the browser over Arrow,
separately from the Vega-Lite spec. Vega's first scale-domain pass therefore runs before
the rows attach, and reports the empty-domain sentinel. Upstream behaviour, warning-level,
no user-visible effect.

**How that was established** — three independent checks, because the previous two
hypotheses were both plausible and both wrong:

1. Every chart's frame was rebuilt offline: 20, 4, 3, 5, 10 and 12 rows. **No chart is
   handed zero rows**, which retires the original hypothesis.
2. Warnings were attributed to charts by patching `console.warn` and recording which
   chart containers had rendered an `<svg>`. **All six warn — including the heatmap at
   `:362`, which never calls `_interactive`.** That retires the correction's two
   candidates: it is not the grouped bar specifically, and selections cannot be involved.
3. **A 20-line vanilla Streamlit app with a clean 5-row frame reproduces it exactly**,
   with and without `theme=None`. No project code required.

**Lesson worth keeping:** the first two attempts both reasoned from the symptom's shape
(`_start`/`_end` implies stacking, therefore a stacked chart) without ever asking *which*
chart emitted it. The attribution in step 2 took one run and immediately falsified both.
Also logged as a gstack learning so a fourth pass does not start over.

**Full detail:** `.gstack/qa-reports/qa-report-localhost-2026-08-01-round3.md`.

### Superseded diagnoses, for the record

This entry previously carried two hypotheses, both written as live work with a priority
and a "start here" pointer. Both were checked and falsified by the evidence above:

1. *(original, 2026-08-01)* "a stacked chart is being handed zero rows" — no chart is.
2. *(correction, same day)* "then it is the grouped bar at `:261` or the legend filter in
   `_interactive`" — it is neither; all six charts warn, including one with no selections.

The full original text is in git history (`49af3ac`) and the reasoning that retired it is
in `.gstack/qa-reports/qa-report-localhost-2026-08-01-round3.md`. Nothing here is
actionable — it is kept only so a future reader recognises the dead end on sight.
