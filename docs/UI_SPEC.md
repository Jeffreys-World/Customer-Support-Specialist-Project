# UI spec — Zendesk Agent Workspace parity

The console is modelled region-by-region on two Zendesk Agent Workspace
screenshots. This file is the checklist that makes "1:1" a claim you can verify
rather than assert.

## Reference images

| File | Screen |
|---|---|
| `docs/reference/zendesk-home.png` | Home / conversation list |
| `docs/reference/zendesk-ticket.png` | Ticket workspace |

Both images are committed, so the comparison below is re-runnable: a future
session can open the reference and the current build side by side rather than
trusting a written description of what the reference looked like.

## How to verify

```bash
streamlit run app.py                      # serves on :8501
BROWSE=~/.claude/skills/gstack/browse/dist/browse

$BROWSE goto http://localhost:8501/
$BROWSE viewport 1440x1750
$BROWSE screenshot .gstack/qa-reports/screenshots/redesign/home.png

$BROWSE goto http://localhost:8501/tickets
$BROWSE js 'document.querySelectorAll("[data-testid=stButton] button")[0].click()'
$BROWSE screenshot .gstack/qa-reports/screenshots/redesign/ticket-detail-full.png
```

Current captures live in `.gstack/qa-reports/screenshots/redesign/`.

## Reference 1 — Home

| # | Zendesk region | Implementation | Data | Status |
|---|---|---|---|---|
| 1.1 | Dark icon rail, full height | `.streamlit/styles.css` → `[data-testid="stSidebar"]`, teal gradient | — | ✅ |
| 1.2 | Product mark, top-left of rail | `st.logo(size="large")` + a CSS height override to 2.9rem (Streamlit caps `large` near 2rem) | — | ✅ |
| 1.3 | Grouped secondary nav | `st.navigation` sections: Home + Dashboard (top level) / Your work / Shared work / Completed work / Account | — | ✅ |
| 1.4 | Recognizable icon per item | Material Symbols via `:material/…` on every `st.Page` | — | ✅ |
| 1.5 | Active item highlighted | `[aria-current="page"]` → lighter fill + blue inset edge | — | ✅ |
| 1.6 | Top bar with title + count chip + avatar | `components.app_bar()` → `.tc-appbar` | real | ✅ |
| 1.7 | Filter dropdowns (Channel / Status / Recommended) | `components.filter_row()` → Search / Priority / Queue / Sort | real | ✅ |
| 1.8 | "8 tickets" list heading | `.tc-section` heading, post-filter count | real | ✅ |
| 1.9 | Conversation row: avatar, name, subject | `components.ticket_row()` → `.tc-row` | subject **and requester name** real; avatar colour derived | ✅ |
| 1.10 | Status pill on each row | `.tc-pill--open` + priority pill | priority real | ✅ |
| 1.11 | Relative timestamp + ticket number | `demo_context._ago()` + `#id` | id real; age simulated | ✅ |
| 1.12 | Tag chips | `.tc-tag` from the dataset's `tags` | real | ✅ |
| 1.13 | Right rail: "Ticket statistics / This week" | "Triage statistics": Critical / High / Past SLA | **real** | ✅ |
| 1.14 | Right rail: "Satisfaction statistics" | "Agreement statistics": confirm vs. override rate. Dataset CSAT is on the Dashboard | **real** | ✅ |
| 1.15 | Profile control at the rail's foot | `components.profile_menu()` → `st.popover` | — | ✅ |

## Reference 2 — Ticket workspace

| # | Zendesk region | Implementation | Data | Status |
|---|---|---|---|---|
| 2.1 | Open-conversation tab strip | `ticket_detail._tab_strip()`, active tab is `type="primary"` | real | ✅ |
| 2.2 | Ticket header: subject + requester + org | `components.app_bar()` with priority chip | subject real | ✅ |
| 2.3 | Left properties panel | Priority (AI), urgency score, suggested queue, safety net, matched signals, tags | **real** | ✅ |
| 2.4 | Conversation thread, avatars + timestamps | `st.chat_message` with initials-avatar data URIs | body real; agent turn simulated | ✅ |
| 2.5 | Amber internal-note block | `components.internal_note()` carrying the AI rationale | **real** | ✅ |
| 2.6 | Right requester card (email, phone, local time, notes) | `components.requester_panel()` | name/email **real**; phone, org, local time, tenure simulated and badged per field | ✅ |
| 2.7 | Interaction history | `components.history_list()` with timeline dots | simulated, badged | ✅ |
| 2.8 | Composer + "Submit as Open" | Reply box, priority select, primary submit → `log_override()` | **decision is real** | ✅ |
| 2.9 | Follow / watch control | `☆ Follow` toggle → Shared work → Following | real | ✅ |

## Deliberate deviations

Each of these is a considered departure, not a gap.

1. **Rows carry an explicit "Open" button** instead of being fully clickable.
   Streamlit provides no click target for arbitrary markup. A visible affordance
   also answers the original complaint — that new users can't tell how to get
   into a ticket.

2. **No Customers / Organizations / Admin rail icons.** The dataset has no
   customer or organization records, so those destinations would be dead ends.
   D2 chose working navigation over a complete-looking rail.

3. **"Satisfaction statistics" became "Agreement statistics."** Written when the
   previous dataset had no CSAT column at all. The current dataset *does* carry a
   satisfaction rating, and it is now shown on the Dashboard with its coverage
   attached (32.7% — only closed tickets are rated). The Home rail keeps
   Agreement statistics, which measures something the Zendesk panel cannot: how
   often the agent kept the AI's priority. Both are real; they answer different
   questions.

4. **"CC'd" is not implemented**, only "Following". CC'd needs a participant list
   the dataset doesn't have.

5. **Replies are not sent.** The composer is present for layout parity and says
   so in its caption. This project triages; it has no outbound mail path.

6. **No "Apply macro" control.** The reference carries one at the bottom-left of
   the ticket workspace. Macros are saved reply templates, which presupposes an
   outbound reply path this project doesn't have (see 5). Adding the button
   without the behavior behind it would be decoration.

7. **No average-resolution-time or volume-over-time chart on the Dashboard.**
   Both were explicitly requested. Neither is computable from this dataset:
   49.3% of closed tickets carry a resolution timestamp *earlier* than their
   first response, and all 8,469 response timestamps fall inside a single 3-day
   window (3 distinct dates). `Date of Purchase` spans two real years but dates
   the purchase, not the ticket. The Dashboard's data-integrity panel states this
   on the page, with figures computed live from the loaded batch. Unresolved rate
   stands in for resolution time — it reads a status column that is fully
   populated. A regression test asserts the omitted chart cannot silently return.

8. **Profile-menu entries are honest about being inert.** "Account settings"
   routes to the real Settings page; View profile, Help & support, and Log out
   each state that they are unimplemented and why (no auth layer, no user
   directory, no help centre). Same standard as 5 and 6.

9. **Notification toggles in Settings are disabled.** There is no outbound mail
   path or scheduler, so enabling them would persist a preference nothing reads.
   The Security panel is likewise a read-only statement of how the build handles
   credentials rather than a set of switches that configure nothing.

## Simulated data

Per D1, everything fed by `ui/demo_context.py` renders a `simulated` badge, and
`Settings` lists the full breakdown of what is real versus derived. Nothing
simulated influences priority, score, signals, the safety net, or the rationale.

Badging is **per field**, not per panel, since the dataset swap. The current
dataset carries a real customer name and email, so stamping the whole requester
card "simulated" would understate what the console knows. `Requester.identity_is_real`
records which way each record went, and only the fields with no source column —
phone, organisation, city, local time, tenure — carry the badge.

## Theme

The console ships light and dark. The rail stays dark teal in both: it is the
shell colour the reference uses, not a light-mode artifact.

Streamlit 1.39 has no runtime theming API, `config.toml` is read once at server
start, and `st.markdown` does not execute `<script>` — so `[data-theme]`
attribute switching is not available. Instead `.streamlit/styles-dark.css`
re-declares the same `:root` custom properties with dark values and is appended
after the base sheet by `ui.theme.inject_css()`, where the later declaration
wins. Any component that references a `var(--tc-*)` is themed for free.

Two consequences worth knowing before editing:

- **Never emit a literal colour into inline markup.** Inline styles cannot be
  overridden by a stylesheet, so a hardcoded hex survives the swap and leaves the
  element wearing light-mode colours on a dark card. `PriorityToken` carries both
  spellings: `var_color`/`var_tint` for markup, and literal `color`/`tint` for
  Altair, which serialises to a Vega-Lite spec and cannot resolve a CSS variable.
- **Charts need `theme=None`.** Streamlit's own Vega theme is applied after the
  spec and restores a white chart background. `dashboard._chart()` pairs
  `configure(background="transparent")` with `theme=None`; use it rather than
  calling `st.altair_chart` directly.

The choice is mirrored into a `theme` query parameter so it survives a browser
reload and travels with a copied URL — session state alone is lost on refresh,
because a reload starts a new Streamlit session.
