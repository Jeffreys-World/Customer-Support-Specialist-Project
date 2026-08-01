---
status: ACTIVE
---
# Design: UI Clarity, Readability, and the Safety-Net Page

Written 2026-08-01. Branch: `feature/data-quality-and-priority-prediction`.

This is the planning record for a batch of nine user-facing changes: what was
asked for, what the code turned out to actually be doing, which implementation
approaches were considered and rejected, and the reasoning behind each decision.
It is deliberately checkable — every claim below carries a file and line
reference, so a reader can verify the diagnosis rather than take it on trust.

## The request

Nine user-facing items, submitted as one list:

1. An info icon on every menu item explaining what that menu does
2. Bigger "Home" title; capitalize the R in "Refund Request"
3. A user control for overall font size
4. Even padding inside the email message box (text touches the border)
5. Safety-net escalations must stop looking identical to Tickets, plus an info icon
6. Move View Profile / Account Settings / Help and Support / Log Out into Settings
7. Dark mode renders text white and unreadable
8. The "Tickets" bar on Home glitches when moved from 3 to 8
9. The "JR" logo top-right is unclickable; give it a function

## What the audit found before the review started

The list is nine symptoms with four already-diagnosed root causes.

| Item | Root cause located during audit |
|---|---|
| 8 | `ui/views/settings.py:141-146` passes both `value=state.attention_limit()` and `key=W_ATTENTION_LIMIT` to `st.slider`, where the `on_change` callback writes the durable key that `value=` is recomputed from. The learning `streamlit-widget-key-gc-kills-cross-page-prefs` documents this exact shape as broken. The selectbox at `settings.py:147-154` carries the identical defect and has not been reported. |
| 7 | `.streamlit/styles.css:149` declares `:root { color-scheme: light; }` and `styles-dark.css` never overrides it. Separately, `ui/views/ticket_detail.py:106` passes `tok.color` (literal hex) to `score_bar_html` where `ui/components.py:166` passes `tok.var_color`; `ui/theme.py:88-99` documents that literal hex in emitted markup cannot be overridden by any stylesheet. Two candidate causes, both real. |
| 3 | Nearly free. `.streamlit/styles.css:114` is `html { font-size: 112.5%; }` with all ~40 sizes in `rem`. But the comment at lines 109-112 warns the ceiling is the fixed 268px nav rail: "Safety-net escalations still sets on one line. Going much past this wraps it." A font-size control that does not also scale the rail ships a wrapped nav label at the first notch. |
| 2 | The lowercase `r` is a dataset value, not our string. `src/data_prep.py:129` puts the raw `Ticket Type` into tags. The same defect affects "Billing inquiry", "Cancellation request", "Product inquiry", and "Technical issue". One title-case at display time fixes all five; editing one string fixes one. |

Confirmed for item 5: `ui/views/tickets.py:171-177` calls the same `render_queue()` as Tickets with a different list. It looks identical because it is identical.

Item 4 could not be resolved statically. `.streamlit/styles.css:336-339` sets `stChatMessage` to `background: transparent; padding: 0.1rem 0`, which has no border for text to touch. The box is either the composer's `st.text_area` card or the `.tc-note` block. Needs a rendered screenshot before a fix is chosen.

**Recurring hot spot:** 19 commits touched `.streamlit/styles.css` in the last 30 days, all `/design-review` and `/qa` finding-fixes. Items 2, 3, 4, and 7 land in that same file. The sheet does token definition, Streamlit shell overrides, and component styling in one place with no test around any of it. That is an architectural smell, not bad luck.

**Not at risk:** nothing here touches `src/rule_scorer.py` or the Critical-class safety-net logic. Item 5 changes only how its results are presented. CLAUDE.md's prime correctness requirement is unaffected.

## Vision

### 10x check

Today the console is a well-built thing that explains itself in a README. The 10x version explains itself on screen, at the moment the question occurs, and the page named after the project's most defensible engineering decision actually shows that decision happening.

Concretely: an agent opens Safety-net escalations and every row says what the ticket scored, what that score would have meant, and which phrase overruled it. "Scored 58, which is Medium. Lifted to 70 by 'system down'." That is the Critical-class safety net arguing for itself in the one place it should, and right now that page is a filtered list with a different title.

Second: the console adapts to its reader. Text size is a control, not a constant, and the setting travels in the URL the way dark mode already does. A reader who needs 20px text gets 20px text on every page, after every refresh, and the nav rail widens to keep its longest label on one line instead of wrapping.

Third: every destination can explain itself without leaving the destination. Seven pages, seven one-click explanations, one component.

### Chosen implementation approach

**Approach C — three coherent workstreams on a preferences substrate.** Selected over "nine independent patches" (A) and "three workstreams, no substrate" (B).

The deciding argument: item 8 is a bug in how a preference persists, and item 3 is a request for a new preference. Shipping 3 on the shape that caused 8 guarantees the bug returns wearing a new label. This repo already paid for that lesson once, as ISSUE-009.

```
COMMIT 1   substrate      ui/prefs.py, ui/state.py, ui/theme.py, settings.py
           (4 files)      one persistence pattern for all four preferences:
                          two-key widget + query-param mirror, generalized from
                          theme.set_dark / theme.is_dark
                          fixes item 8 at the root, plus the unreported twin
                          defect in the default-sort selectbox
                          no visible change; tests prove persistence survives nav

W1         readability    styles.css, styles-dark.css, theme.py, components.py,
           (5 files)      ticket_detail.py            -> items 3, 2, 7, 4

W2         explain        components.py + 7 view call sites
           (8 files)      -> items 1, 5, E1

W3         account & nav  app.py, components.py, settings.py
           (3 files)      -> items 6, 9
```

Rejected alternatives, with reasons:

- **A (nine independent patches).** Human ~2 days / CC ~40 min. Smallest diff per item, easiest single-item review. Rejected: item 3 reintroduces item 8's bug in a new widget, item 2 fixes one of five lowercase dataset values, items 6 and 9 build two account controls where one belongs, and item 5 duplicates item 1's help pattern.
- **B (workstreams, no substrate).** Human ~3 days / CC ~60 min. Groups by mechanism and resolves the 6/9 collision. Rejected: leaves four preferences on three persistence strategies with no test around any of them.

## Scope decisions

| # | Proposal | Effort (human / CC) | Decision | Reasoning |
|---|----------|--------|----------|-----------|
| E1 | Safety-net page shows the lift per ticket: raw score, what it would have been, which trigger fired | ~4h / ~15 min | **ACCEPTED** | The arithmetic already exists in `domain.scorer_worked_example()` but is computed for one hardcoded sentence and thrown away. Item 5 as written is "make it look different"; this makes it mean something different. It is the screenshot a hiring manager takes. |
| E2 | Visual-regression snapshot: 4 shots (Home, Ticket detail) x (light, dark), pixel-diffed against a committed baseline | ~1 day / ~25 min | **ACCEPTED** | TODOS.md already calls the `.st-key-*` CSS-scoping mechanism "the one failure mode in the whole redesign that is untested, unhandled, AND silent." Item 9 adds a second load-bearing use of it, and W1 rewrites the type scale across 40 sizes with nothing asserting how it renders. |
| E3 | ARIA pass on the ~13 new interactive controls this plan introduces | ~4h / ~15 min | **ACCEPTED** | Items 1, 5, 6, and 9 add roughly 13 controls. TODOS.md deferred the ARIA audit when the app had fewer. Also catches a concrete defect: `components.py:127` renders the JR avatar `aria-hidden="true"`, and item 9 makes it a button. A focusable element hidden from the accessibility tree is worse than an inert one. |
| E4 | Mirror all four preferences into the URL so a link reproduces the exact view | ~3h / ~10 min | **DEFERRED** | `ui/views/settings.py:160-165` already decided against this with a stated reason: "a shared link carrying someone else's list length would be surprising rather than useful." Reversing a settled call needs a better reason than "the substrate makes it cheap." Font scale alone is mirrored, as baseline inside item 3, because it is an accessibility preference like dark mode. |
| E5 | `humanize()` applied to every dataset value, not just "Refund request" | ~2h / ~10 min | **BASELINE** | Not an expansion. Approach C was selected on the argument that one display-time title-case fixes all five ticket types; the user chose that approach, so this is inside item 2. |

## Accepted scope

Baseline (the nine as submitted, read through approach C):

- **Item 1** — a `page_help` component, one call site per destination. Generalizes the expander pattern already at `ui/views/tickets.py:161`, rather than inventing a second one.
- **Item 2** — the type scale's top step moves (which is item 3's mechanism, so not separate work), and every dataset value routes through one display-time title-caser. Fixes "Refund request", "Billing inquiry", "Cancellation request", "Product inquiry", "Technical issue".
- **Item 3** — a font-size preference on the prefs substrate, mirrored into the URL, driving `html { font-size }`. The nav rail width scales with it so "Safety-net escalations" keeps setting on one line.
- **Item 4** — even padding in the message box, after a rendered screenshot identifies which box.
- **Item 5** — distinct layout and header for Safety-net escalations, plus a `page_help` call site.
- **Item 6** — account entries move into Settings.
- **Item 7** — dark-mode text legibility, addressing the `color-scheme: light` override and the literal-hex call site.
- **Item 8** — fixed at the root by commit 1, along with the unreported selectbox twin.
- **Item 9** — the JR avatar becomes the account control.

Accepted expansions:

- **E1** — per-ticket lift display on Safety-net escalations
- **E2** — visual-regression snapshot covering both themes
- **E3** — ARIA pass on the new controls

### One design call folded into the baseline

Items 6 and 9 arrived as separate requests and resolve into one move. Item 6 removes the profile menu from the rail foot; item 9 asks for a function on the top-right JR avatar. Every SaaS product puts the account menu behind exactly that avatar, and `ui/components.py:112-129` already renders it there as the identity marker. So: the avatar becomes the account control, Settings gains the account panel, and the rail-foot popover retires. That is one coherent control instead of two unrelated ones, and it means item 9 does not need to invent a "go to dashboard" behavior the rail already provides one click away.

## Deferred to TODOS.md

- **E4 — URL-mirrored view state for attention limit and default sort.** The substrate makes it cheap, but `settings.py:160-165` argues against it on product grounds and that argument still holds. Revisit if the console ever gets shared links in a README. Font scale is exempt and ships mirrored, because an accessibility preference that resets on refresh is a defect rather than a preference.

## Decisions from the 11-section review

| # | Finding | Decision | Reasoning |
|---|---------|----------|-----------|
| 1 | **F6.1** E2's pixel baseline fails across Windows/macOS | **1A** — assert DOM structure and computed styles, not pixels | `ui/components.py:574-580` already rejected emoji for this exact cross-OS reason, and there is no CI to pin a generator machine. Computed-style assertions catch the silent degradation TODOS.md names without inheriting font rasterization differences. Screenshots still written for human review. |
| 2 | **F4.1** Most escalated tickets fired the net but were not lifted by it | **2A** — two distinct row states | `ui/domain.py:331-339` computes `fired` and `lifted_to_floor` as different counts because they are different facts. "Scored 82 on keywords alone; 'data loss' would have forced High regardless" is the case that shows the net agreeing with the scorer, which is itself evidence the scorer works. |
| 3 | **F5.1 / F5.3** Item 5 needs a different header, rail, and row than Tickets | **3A** — inject the varying parts as callables | `render_queue` already carries five parameters. The filter strip, paging, and filtered-count header each encode a specific bug fix (ISSUE-001, ISSUE-012, the empty-state early return) and must stay shared; only the row and rail get passed in. |
| 4 | **F3.1** Font-scale value reaches an unsanitized `<style>` block | **4A** — fixed name-to-value map, unknown key falls to default | The URL supplies a key; the CSS value is a literal in our source. Nothing user-supplied enters the `<style>` block at all, so there is nothing to escape and nothing to regress. Same shape `theme.is_dark()` already uses. |
| 5 | **F1.1** Import layering for `ui/prefs.py` | **5A** — prefs is the base layer; theme and state import it | `is_dark` / `set_dark` move out of `theme.py`, which returns to being purely about how things look, as its own docstring already claims. `inject_css` needs the font scale, so prefs must sit below theme or the dependency inverts into another local-import workaround. |
| 6 | **F11.1** Seven help popovers is the highest AI-slop risk in the plan | **6A** — page-specific answers drawn from existing docs | Seven controls that each restate the page title would cheapen a repo whose character is documenting its own rejected alternatives with measurements. Every answer already exists in `docs/UI_SPEC.md`, the Settings captions, or the scorer explainer. Assembly, not authorship. |
| 7 | **F2.1 / F2.2 / F1.2 / F4.2** Four hardening fixes in touched areas | **7A** — include all four | F2.1 is a crash before first paint in the exact code item 9 edits. The others are a silent unstyled-app path, ~40KB of uncached disk I/O per click (three files after item 3), and the session keys item 6 orphans. |
| 8 | **F10.1** `styles.css` at 1034 lines, 19 commits in 30 days | **8A** — record the split in TODOS.md, do not do it now | Splitting a stylesheet with nothing asserting how it renders is the change most likely to break styling silently. Order: this plan lands, then the computed-style assertions, then the split. |

### Findings recorded without a separate decision

- **F1.3** `st.navigation` cannot host item 1's icon. Streamlit renders the rail links itself and `st.markdown` does not execute `<script>` (`ui/theme.py:191-204`). The affordance lives in the app bar beside the page title.
- **F1.4** `.streamlit/styles.css:213` hard-codes `width: 268px !important`. The rail width becomes a token that scales with the type scale, or the longest nav label wraps — which the stylesheet's own comment at lines 109-112 already predicted.
- **F1.5 / F9.1** `browse` is a dev tool resolved via `find-browse`, not a runtime dependency. It must not enter `requirements.txt`, and the snapshot test skips with a stated reason when it is absent rather than hard-failing a fresh clone.
- **F8.1** `ui/components.py:508-516` measures the safety-net invariant on every render rather than asserting it. Item 5 restructures that page. **The invariant check must survive the redesign.**
- **F11.2** Responsive behaviour is unverified at the largest font size: 137.5% base on a 375px viewport puts four large numerals in ~355px, with the rail as an overlay.

## Open question carried into implementation

**Item 4 is unresolved statically.** `stChatMessage` has `background: transparent` and no border, so it is not the box described. The two candidates are the composer card at `ui/views/ticket_detail.py:178-184` and the `.tc-note` block at `.streamlit/styles.css:650-657`. Resolve by rendering the ticket detail view and looking, before writing any CSS.

## Round 2 — interaction states, 2026-08-01 (HOLD SCOPE)

A second review after `/qa` fixed four bugs. Four new asks: a clickable info icon for
the explainer, fix its wording, improve every menu and toggle, and reach a 100% health
score.

### The measurement that reframed it

| Interaction state | Rules in `styles.css` | Controls needing them |
|---|---|---|
| hover | 13 | 33 |
| **focus** | **1** | **33** |
| active | 0 | 33 |
| disabled | 0 | 3 ship `disabled=True` |

The single focus rule is `styles.css:1032`, scoped to
`[data-testid="stMainBlockContainer"] [data-testid="stButton"] button`. It covers buttons
in the workspace and nothing else: not the 7 nav links, not the popover, not a single
toggle, slider, select, multiselect, input, or expander. A keyboard user sees a focus
ring on roughly 1 of 33 control types.

**This is ISSUE-001's bug in a different property.** That was a dark-mode rule scoped to
`stMain` that missed a portaled popover. This is a focus rule scoped to
`stMainBlockContainer` that misses everything outside it. Colour got fixed; focus was
never written. The scoping trap is systemic, which is why the contract below is written
against control *classes* rather than DOM paths.

### On the 100% health score

Raised once, then executed as asked. The score is a rubric applied to defects one
reviewer chose to look for, so optimising it directly optimises a proxy. Concretely: the
96 reported after `/qa` was overstated, because Accessibility was scored 100 without ever
auditing focus states. Scored honestly against the table above, Accessibility is 85 and
the overall is ~94. The first honest step toward 100 lowers the number.

The target adopted instead, which reaches 100 on the same work but survives new
discovery: **zero known open defects, and WCAG 2.2 AA on every interactive control** —
an external spec with pass/fail criteria, asserted in the suite rather than asserted by
a reviewer.

### Decisions

| # | Finding | Decision | Reasoning |
|---|---------|----------|-----------|
| 1 | `--tc-primary` (#1F73B7) on the rail (#03363D) measures **2.62:1**, below WCAG 2.2 SC 1.4.11's 3:1 floor for focus indicators | **1A** — two tokens, `--tc-focus-ring` and `--tc-focus-ring-rail`, plus a unit test failing below 3.0 | One token cannot serve both surfaces, and the 7 nav links live on the failing one. The test is what turns the standard into a guarantee instead of a memory. |
| 2 | Three notification toggles ship permanently `disabled=True` | **2A** — cut them, keep a one-line statement | A control that cannot be operated has not earned its pixels. The Security panel already uses statements over dead switches. Also removes 3 of the 33 controls the contract must cover. |
| 3 | The explainer sits behind a 47-character collapsed expander | **3A** — info icon in the app bar, expander retires, popover heading becomes "How a ticket gets escalated" | The grammar problem dissolves rather than being reworded, and this is T8's component, so the other six pages get their icon from the same build. |
| 4 | A focus ring on the slider is a lie until ISSUE-002 is fixed | **4A** — T1/T2 first, then define, apply, assert | `/qa` measured focus dropping to `<body>` after every slider change. A ring on that control tells the user they hold the handle when they do not. |

### Scope note

These four asks need **11 tasks**; the plan above has 17. The other six (T3/T4 font
scale, T7 message-box padding, T10 account control, T14 mobile-at-largest-font) come
from the earlier nine-item list and are not required by anything in round 2. Carried,
not cut, but named so the commitment is visible.

### Build order

```
  1. T1   ui/prefs.py substrate
  2. T2   slider + selectbox stop remounting        <- unblocks the ring AND point 4
  3.      interaction contract: 4 states x each control class, as tokens
  4.      apply to all 30 controls (33 minus the 3 cut)
  5.      assert: focus rule per class + focus-ring contrast >= 3:1 both surfaces
  6. T8   page_help component + 7 call sites         <- points 1 and 2
  7. T6   humanize()   T9 safety-net + lift   ISSUE-008 chart   <- point 4 exit criteria
  8. T11  ARIA names   T13 stale comments
```

### Open risk carried into implementation

The CSS assertion proves *our sheet declares a rule*. It cannot prove *Streamlit still
emits that testid*. A version bump renaming `stBaseButton-secondary` leaves the test
green and the focus ring gone — the same silent-degradation class TODOS.md already
tracks. Pair the CSS assertions with at least one rendered check.

## What this plan did not get

An independent second-model review of this document did not run — the tool that
provides it was not installed on the machine this was written on. So every finding
here comes from one reviewer reading the source directly, not from two reviewers
agreeing. That is worth knowing when weighing the confidence of anything above,
which is why it is recorded here rather than left out.

Every claim carries a file and line reference specifically so it can be checked
without trusting the reviewer.
