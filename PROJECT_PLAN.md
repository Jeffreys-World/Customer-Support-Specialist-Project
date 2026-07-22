# Jordan's Ticket Triage Assistant — Project Plan

## 1. Problem

Jordan, a Customer Support Representative, struggles with manually reviewing, prioritizing, and categorizing 200–300 support tickets each week because the organization does not use its existing support data to automate ticket classification and prioritization, which means valuable time is lost each morning, critical issues are delayed, and customer satisfaction suffers.

## 2. Solution

An automated triage layer that classifies every incoming ticket by priority (Critical/High/Medium/Low) with a 0–100 urgency score and a plain-language rationale, **before** Jordan ever opens the queue. Jordan opens an already-sorted list instead of triggering AI review ticket-by-ticket. The agent always has final say — the system recommends, it doesn't decide.

## 3. Architecture

```
Ticket source (CSV/dataset, simulating incoming tickets)
        │
        ▼
[1] Rule-based scorer  ──► deterministic score (0-100) + category
        │
        ▼
[2] LLM rationale layer (Claude API) ──► human-readable "why" + queue suggestion
        │
        ▼
[3] Batch classification job ──► writes results to classified_tickets store
        │
        ▼
[4] Streamlit UI ──► sorted queue view, ticket detail, confirm/adjust, override log
```

Why split rule-based scoring from LLM rationale: the score itself needs to be reliable and cheap to run on 200–300 tickets; the LLM's job is explaining the score in plain language, not inventing it. If the LLM step fails or costs run out, the rule-based score still works and the queue still sorts correctly — no single point of failure.

## 4. Tech Stack

- Python 3.11+
- Streamlit (UI)
- pandas (data handling)
- anthropic Python SDK (Claude API for rationale generation)
- python-dotenv (API key management)

Trade-off accepted: Streamlit won't pixel-match Zendesk's UI. We'll approximate its color palette/typography via `st.markdown` + custom CSS rather than building a full custom frontend — keeps 2-week scope realistic.

## 5. Data

**Source:** [Customer IT Support Ticket Dataset (Kaggle)](https://www.kaggle.com/datasets/tobiasbueck/multilingual-customer-support-tickets) — labeled email tickets with priority, queue, tags, and business type.

**Backup:** [Support Ticket Priority Dataset (50K)](https://www.kaggle.com/datasets/albertobircoci/support-ticket-priority-dataset-50k) if the primary dataset needs supplementing.

**Scope decision — English only:** the primary dataset is multilingual. Keyword-based scoring won't work on non-English text, so Day 1–2 includes filtering the dataset down to English-language tickets only. This is a stated scope limitation for the two-week build, not a bug to fix later.

**Ground truth for evaluation:** the dataset's existing priority labels are treated as ground truth. The rule-based scorer's output is what gets evaluated against them (the LLM layer only generates rationale text, it doesn't set the category — see Section 10).

**Priority mapping** (dataset → product card scale):

| Dataset label | Product card category | Score range |
|---|---|---|
| Critical | 🔴 Critical | 90–100 |
| High / Medium (dataset dependent — confirm during exploration) | 🟠 High | 65–89 |
| Low-Medium | 🟡 Medium | 35–64 |
| Low | 🟢 Low | 0–34 |

Exact mapping gets finalized once the dataset is loaded and its label distribution is inspected (Day 1–2).

## 6. Repo Structure

```
jordan-triage/
├── .env                      # ANTHROPIC_API_KEY (gitignored)
├── requirements.txt
├── data/
│   └── raw/                  # downloaded Kaggle CSV
│   └── processed/            # cleaned + mapped ticket data
├── src/
│   ├── rule_scorer.py        # keyword/heuristic scoring logic
│   ├── llm_rationale.py      # Claude API call + prompt template
│   ├── batch_classify.py     # runs scorer + rationale over a batch, writes results
│   └── schema.py             # shared data structures
├── app.py                    # Streamlit UI entry point
└── README.md
```

## 7. Component Specs

**Rule-based scorer (`rule_scorer.py`)**
Input: ticket subject + body. Output: `{score: int, category: str, matched_signals: list[str]}`.
Keyword sets per category (starting point, refine after seeing real data):
- Critical: "outage", "down", "can't log in", "security", "breach", "locked out", "payment failed", "urgent"
- High: "broken", "not working", "multiple users", "error", "billing issue"
- Medium: "question", "how do I", "slow"
- Low: "feature request", "documentation", "feedback"
Score = weighted count of matches + escalation for repeated/duplicate customer mentions.

**Critical safety net (highest-priority design rule):** the costliest failure mode is a Critical ticket getting misread as routine — that's exactly what happened to Jordan with the billing issue that sat for 4 hours. So this isn't optional: any ticket containing a hard-trigger signal (outage, down, can't log in, security, breach, locked out, payment failed) is force-escalated to at least High regardless of overall score. Optimize this scorer for **recall on the Critical class** first, general accuracy second.

**LLM rationale layer (`llm_rationale.py`)**
Prompt template: given ticket text + rule-based score/category, ask Claude to output JSON: `{rationale: [bullet, bullet], suggested_queue: str}`. The LLM does not re-decide the score — it explains the score it's given. This keeps LLM output constrained and cheap (short completions, no open-ended classification).

**Batch classification job (`batch_classify.py`)**
Simulates "tickets arriving overnight" — reads the ticket dataset, runs every ticket through steps 1 and 2, writes a results file the UI reads from. This is the piece that replaces the "click AI Assistant per ticket" flow with auto-sorting.

**Streamlit UI (`app.py`)**
- Queue view: table sorted by score/category, Zendesk-ish color accents, countdown/age indicator
- Detail view: click a ticket → see rationale bullets + suggested queue
- Confirm/Adjust control: agent can accept or override the category — logged for the manual spot-check evaluation described in Section 10 (there's no live agent generating this data at production scale, so we generate it ourselves by reviewing a sample)

## 8. Two-Week Plan

**Week 1 — working pipeline**
| Day | Task | Done when |
|---|---|---|
| 1–2 | Download dataset, filter to English-only tickets, explore label distribution, finalize priority mapping, set up repo + venv, claim Anthropic $5 credit, do a rough token-cost estimate for running rationale generation on the full batch | `data/processed/tickets.csv` exists with mapped priority column; cost estimate confirms the batch fits inside the $5 credit |
| 3–4 | Build rule-based scorer | Running it on 20 sample tickets produces sensible scores/categories |
| 5–7 | Build LLM rationale layer + batch job | Full dataset batch runs end-to-end, produces `classified_tickets.json` with score, category, rationale, queue for every ticket |

**Week 2 — UI, testing, packaging**
| Day | Task | Done when |
|---|---|---|
| 8–9 | Build Streamlit queue view + detail view + confirm/adjust | Can open app, see sorted queue, click a ticket, see rationale, override a category |
| 10–11 | Run full batch, score rule-based output against dataset ground-truth labels (accuracy + precision/recall by category), tune thresholds — prioritize Critical-class recall over overall accuracy, then manually spot-check ~20–30 tickets and log agree/disagree | Critical-class recall and overall accuracy are both computed and reported as real numbers, not estimated |
| 12–13 | Write before/after narrative, build demo script/slides | Can walk through: "Jordan used to spend 1.5 hrs sorting → now opens a pre-sorted queue" with the billing-ticket scenario as the hook |
| 14 | Buffer — fix breakage, rehearse demo | Demo runs clean twice in a row |

## 9. Stretch Goals (only if Week 1–2 finishes early)

- Real Zendesk sandbox integration (pull live tickets via API instead of static dataset)
- Lightweight trained classifier (e.g. logistic regression on TF-IDF) as an alternative/comparison to the rule-based scorer
- SLA countdown timer per ticket in the UI

## 10. Success Metrics for the Demo

These are the numbers the demo needs to actually produce — not impressions, computed results:

- **Critical-class recall** (of all tickets the dataset labels Critical, what % did the rule-based scorer also flag Critical or higher): this is the metric that matters most, since a miss here is exactly Jordan's 4-hour billing scenario. Target: as close to 100% as the safety-net keyword list allows.
- **Overall classification accuracy**: rule-based scorer's category vs. the dataset's ground-truth priority label, reported with a confusion matrix (not just a single %) so misclassification patterns are visible.
- **Manual spot-check agreement rate**: reviewer (you) manually judges ~20–30 tickets and compares to the AI's output — framed explicitly as a small-sample sanity check, not a production feedback metric, since there's no live agent generating this data yet.
- **Time-to-sorted-queue**: instant vs. Jordan's 1.5 hours (qualitative/narrative point, not a measured metric).
- **The billing-ticket scenario**, re-run through the system, correctly flagged Critical by the safety net — used as the concrete "here's the exact problem this solves" demo moment.

**Known limitations to state upfront in the demo** (own these rather than let them surface as surprises): English-only ticket coverage, keyword lists tuned to a generic IT-support dataset rather than a real company's product taxonomy, and no live production feedback loop yet.

## 11. Git & Documentation Strategy (for a hiring-manager audience)

**Commit cadence.** One meaningful commit per completed stage, not continuous "wip" commits — a hiring manager should be able to read the commit log top to bottom and understand the whole build without opening a single file. Use [Conventional Commits](https://www.conventionalcommits.org/) style (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).

| Stage | Commit message (example) |
|---|---|
| Repo/data setup | `chore: initialize project, load dataset, filter English-only tickets, map priority labels` |
| Rule-based scorer | `feat: rule-based priority scorer with Critical-class safety net` |
| LLM rationale layer | `feat: add Claude API rationale generation and batch classification pipeline` |
| Streamlit UI | `feat: build triage queue UI with confirm/adjust control` |
| Evaluation | `test: evaluate scorer accuracy, confusion matrix, and Critical-class recall` |
| Documentation | `docs: add README with architecture, results, and demo instructions` |

Tag the final commit `v1.0` once everything above is merged and working.

**README.md (repo-facing, technical audience).** Structure:
1. One-line pitch + the Jordan problem statement, quantified (200–300 tickets/week, 1.5 hrs lost daily, the 4-hour Critical-ticket incident)
2. What it does (1 screenshot or GIF of the sorted queue)
3. Results — the real numbers from Section 10 (Critical-class recall, accuracy, confusion matrix), not just a description
4. Architecture diagram (reuse Section 3 of this plan)
5. Tech stack
6. Setup/run instructions
7. Live demo link (see below)
8. Limitations & what I'd build next
9. Author contact / link back to portfolio

**Portfolio case-study page (narrative, non-technical audience).** Shorter and less code-heavy than the README — this is what actually gets read by a hiring manager skimming a portfolio site:
1. The hook: Jordan's problem in plain language
2. Process: the 5-Whys root cause work (shows product thinking, not just coding)
3. What I built (screenshot)
4. Impact: the measured results
5. What I'd do differently / next steps
6. Links: GitHub repo + live demo

**Live demo (recommended addition).** Deploy the Streamlit app to [Streamlit Community Cloud](https://streamlit.io/cloud) (free) so a hiring manager can click and try it rather than just read about it — this is one of the highest-value, lowest-effort additions for a portfolio piece. Add as a task once the UI is stable (end of Week 2).
