# Instructions for Claude Code

This project builds "Jordan's Ticket Triage Assistant." Full context, architecture, data mapping, and the two-week build plan live in `PROJECT_PLAN.md` — read that first before writing any code.

This repo will be shown to hiring managers on a portfolio site, so process and documentation matter as much as the working code. Follow these rules throughout the build, not just at the end:

## Git workflow

- Initialize git on the first run if not already a repo.
- Make **one commit per completed stage**, not continuous small "wip" commits. A stage is done when its "Done when" criteria in `PROJECT_PLAN.md` Section 8 is met.
- Use Conventional Commits style (`feat:`, `fix:`, `docs:`, `test:`, `chore:`). See `PROJECT_PLAN.md` Section 11 for the exact commit sequence to follow.
- Never commit `.env`, API keys, or secrets. Confirm `.gitignore` covers `.env`, `__pycache__/`, and `data/raw/` before the first commit.
- Tag the final working commit `v1.0`.
- Before each commit, briefly state in chat what stage just completed and what the commit message will be, so progress is visible.

## Build order

Follow the day-by-day plan in `PROJECT_PLAN.md` Section 8 in order — don't skip ahead to the UI before the rule-based scorer and its Critical-class safety net (Section 7) are working and tested. The Critical-class safety net is the single most important correctness requirement in this project; do not treat it as optional or defer it.

## Evaluation

Section 10 of `PROJECT_PLAN.md` defines the required metrics: Critical-class recall, overall accuracy with a confusion matrix, and a manual spot-check log. These must be computed and saved (e.g. to `results/evaluation.md` or similar) as real output, not just printed and discarded — they're needed for the README and portfolio write-up.

## Documentation (build this incrementally, not as an afterthought)

- Update `README.md` as each major piece lands, following the structure in `PROJECT_PLAN.md` Section 11 — don't leave it all for the last day.
- Once the evaluation numbers exist (end of Week 2), the README's "Results" section must show the actual computed numbers, not placeholders.
- If time allows, deploy the Streamlit app to Streamlit Community Cloud and add the live link to the README.

## Tools

- **Bash**: run Python, pip installs, the Kaggle CLI download, `streamlit run`, `pytest`, and all git commands.
- **Read/Write/Edit**: source files.
- **Grep/Glob**: navigate the codebase as it grows past a handful of files.
- **WebSearch/WebFetch**: look up exact syntax for the Anthropic Python SDK, Streamlit APIs, or Kaggle API docs rather than guessing — cheaper than debugging a hallucinated API call.
- **TodoWrite**: at the start of each session, sync your todo list to the current stage in `PROJECT_PLAN.md` Section 8, so progress carries across sessions over the two weeks.

## Subagents

Three custom subagents live in `.claude/agents/` in this project. Delegate to them explicitly rather than doing everything in the main session:

- **code-reviewer** — invoke before every commit. It checks the stage's code against its "Done when" criteria, confirms the Critical-class safety net is intact, and checks no secrets are staged.
- **evaluator** — invoke for all of Section 10's evaluation work (Critical-class recall, accuracy, confusion matrix, spot-check). Keep evaluation logic and reporting in this agent's hands so results stay consistent and honestly reported.
- **docs-writer** — invoke after each commit-worthy stage to keep README.md and the portfolio case study updated incrementally, and again once evaluator produces real numbers, to replace any placeholder text.

For ad hoc code search across the growing codebase, Claude Code's built-in **Explore** subagent (fast, read-only) is enough — no need for a custom one.

## Scope discipline

If something in `PROJECT_PLAN.md` isn't working within its allotted days, fall back to the simplest version that still meets the "Done when" bar rather than over-engineering — the buffer day (Day 14) exists for fixes, not for new scope. Flag any deviation from the plan in chat before making it, rather than silently changing course.
