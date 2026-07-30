# Jordan's Ticket Triage Assistant

**An automated triage layer that sorts a support queue by priority — with a
plain-language "why" — before an agent ever opens it.** The queue arrives
pre-sorted instead of the agent running an AI review ticket-by-ticket. The
system recommends; the agent always has final say.

## The problem (quantified)

Jordan is a Customer Support Representative who manually reviews, prioritizes,
and categorizes **200–300 tickets a week**. Sorting the morning queue by hand
costs about **1.5 hours a day**, critical issues get buried, and once a
payment-failure ticket sat unread for **4 hours** because nothing surfaced it.
The organization already has labeled support data — it just wasn't being used to
triage automatically.

## What it does

1. A deterministic **rule-based scorer** assigns every ticket a 0–100 urgency
   score and a category (🔴 Critical / 🟠 High / 🟡 Medium / 🟢 Low).
2. A **Critical-class safety net** force-escalates any ticket containing a
   hard-priority signal (outage, breach, payment failed, locked out, …) to at
   least High — regardless of its score. This is the single most important rule
   in the system.
3. A **Claude rationale layer** explains the score in one or two bullets and
   suggests a queue. It *explains* the score; it never re-decides it.
4. A **batch job** runs the whole dataset overnight into `classified_tickets.json`.
5. A **Streamlit console** modelled on Zendesk's Agent Workspace shows the
   pre-sorted queue, a full ticket workspace, and a confirm/adjust control that
   logs every agent override.

### The console

A dark navigation rail with grouped menus (Your work / Shared work / Completed
work / Account), a Home view, a filterable queue, and a three-column ticket
workspace: properties on the left, the conversation and the AI rationale as an
internal note in the middle, requester context on the right. Plus a **Dashboard**
of ticket analytics, a profile menu, and a dark mode.

Region-by-region parity against the Zendesk reference is tracked in
[`docs/UI_SPEC.md`](docs/UI_SPEC.md).

### The Dashboard, and the two charts that aren't on it

The Dashboard carries KPI tiles (open, awaiting customer, unresolved rate,
satisfaction, Critical), ticket volume by type and priority, channel and status
distribution, a satisfaction histogram, top products, and a priority-against-
status heatmap.

It does **not** carry average resolution time or ticket volume over time, and it
says so on the page. Neither is computable from this dataset without inventing
numbers: 49.3% of closed tickets record a resolution *earlier* than their first
response, and every response timestamp in 8,469 rows falls inside a single 3-day
window. A "Data integrity" panel states this in the product, with the figures
computed live from the loaded batch rather than transcribed from a one-off
analysis.

That panel is the most useful thing on the page. Details below.

```
🔴 Critical  92  Payment failed on renewal, account locked out   Billing and Payments   ⚠️ breached  🛡️
🟠 High      71  Production API returning 500s for all users      Technical Support      3.1h left   🛡️
🟡 Medium    48  How do I export my report to PDF?                General Inquiry        18h left
🟢 Low       29  Feature request: dark mode would be nice         Product Support        60h left
```

### Real data vs. simulated demo data

The console's layout follows Zendesk, which displays requester identity,
conversation threads, and interaction history. Where the dataset has no source
column, panels are filled with values derived deterministically from the ticket
id and render a `simulated` badge. The Settings page lists the full breakdown.

| Real | Simulated for demonstration |
|---|---|
| Priority, urgency score, category | Requester phone, organization, city, local time |
| Matched keyword signals | Agent reply turns in the thread |
| Critical-class safety-net state | Interaction history |
| AI rationale and suggested queue | Ticket age and the SLA countdown |
| Subject, body, tags, four-level ground-truth label | |
| Requester name and email | |
| Ticket status, channel, type, product | |
| Customer satisfaction rating (closed tickets only) | |
| Your confirm/override decisions, and the agreement statistics computed from them | |

Nothing in the simulated column influences triage.

## Results (measured, not estimated)

Evaluated on all **8,469 tickets** in the Kaggle customer-support dataset,
comparing the rule-based scorer to the dataset's own four-level `Ticket Priority`
label. Full report: [`results/evaluation.md`](results/evaluation.md).

**The scorer performs at chance on this dataset. That is a property of the
dataset, not a bug in the scorer, and this section exists to prove the
difference.**

| Metric | Value | Baseline |
|---|---|---|
| Overall accuracy (4-way) | **26.0%** | 25.0% by chance |
| **Critical-class recall** — of `Critical` tickets, % flagged Critical or High | **28.4%** | 27.9% — the rate the scorer flags *anything* top-severity |
| Top-severity recall (`Critical` + `High`) | 28.8% | — |

Confusion matrix (truth ↓ / prediction →):

| | Critical | High | Medium | Low |
|---|---|---|---|---|
| **Critical** | 173 | 432 | 1,067 | 457 |
| **High** | 170 | 437 | 1,050 | 428 |
| **Medium** | 158 | 419 | 1,140 | 475 |
| **Low** | 147 | 427 | 1,035 | 454 |

Read the rows, not the diagonal. They are nearly identical — the scorer emits the
same distribution of predictions whether the ticket is truly Critical or truly
Low. That shape, not the accuracy figure, is the finding.

**Why no classifier could do better here.** Two chi-square tests of independence:

| Test | chi² | dof | Cramér's V |
|---|---|---|---|
| Scorer prediction × true label | 7.0 | 9 | 0.017 |
| **Ticket subject × true label** | **40.9** | **45** | **0.040** |

Both statistics sit at or below their degrees of freedom, which is what pure
independence looks like — under the null hypothesis the expected value of chi² *is*
dof. The second row does not involve the scorer at all: the ticket's own subject
line does not predict its priority. The dataset ships **16 distinct subject
lines** across 8,469 tickets and a templated body whose `{product_purchased}`
placeholder was never interpolated in the source file. The text and the labels
were generated independently, so there is no signal for any model to learn.

**What is still provably true.** The Critical-class safety net fired on **1,525
tickets (18.0%)**. It is a deterministic guarantee about vocabulary, not a
prediction: **every ticket containing a hard-priority signal escalates to at
least High**, verified by parametrized tests (`tests/test_rule_scorer.py`). What
this dataset removes is the ability to *measure* whether escalation correlates
with the label, because the label correlates with nothing. The mechanism is
intact; the measuring stick is broken.

**On the previous dataset.** An earlier version of this project ran on a
multilingual Kaggle set of 11,923 English tickets and reached 49.2% top-severity
recall at 41.6% accuracy. That dataset had no `Critical` label and none of the
status, channel, or satisfaction columns the Dashboard needs. The swap traded a
better-looking headline for a dataset that supports the product — and surfaced a
label-quality problem worth reporting. Both are in the git history.

## Architecture

```
Ticket source (customer_support_tickets.csv — 8,469 rows, 17 columns)
        │
        ▼
[1] Rule-based scorer  ──► deterministic score (0-100) + category + safety net
        │
        ▼
[2] Claude rationale layer ──► human-readable "why" + suggested queue
        │
        ▼
[3] Batch classification job ──► classified_tickets.json
        │
        ▼
[4] Streamlit UI ──► sorted queue, ticket detail, confirm/adjust, override log
```

The scorer and the LLM are deliberately separate (PROJECT_PLAN.md §3): the score
must be reliable and cheap to run on 200–300 tickets; the LLM only explains it.
If the API key is missing or a call fails, the batch job degrades to a
deterministic rule-based rationale — the queue still sorts correctly. No single
point of failure.

## Tech stack

Python 3.9+ · pandas · Streamlit · Altair · Anthropic Python SDK
(`claude-opus-4-8`, structured JSON output) · python-dotenv · pytest.

Chi-square and Cramér's V are implemented directly in `src/evaluate.py` rather
than pulled from scipy — a heavy dependency for two functions in a Streamlit app.
They are verified against known critical values (chi²=3.841 at 1 dof → p=0.0500)
and against V=1.0/0.0 on perfectly dependent and independent inputs.

## Setup & run

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 1. Build the working set from the raw Kaggle CSV
#    (place customer_support_tickets.csv in data/raw/ first)
python -m src.data_prep

# 2. Classify the batch (score-only; no API key needed)
python -m src.batch_classify

# 3. Launch the triage console
streamlit run app.py

# 4. Reproduce the evaluation numbers
python -m src.evaluate

# 5. Run the test suite (safety net + UI smoke test)
pytest -q
```

### Regenerating the committed demo sample

A fresh clone has no `classified_tickets.json`, so the console falls back to
`classified_tickets.sample.json`. That sample must span all four priorities —
`--limit` slices the head of an already-sorted list and would return only
Critical tickets, leaving the priority filter with nothing to filter:

```bash
python -m src.batch_classify --stratified 800 \
  --output data/processed/classified_tickets.sample.json
```

The draw is proportional to the real distribution and fully deterministic, so
regenerating it produces a byte-identical file.

### Optional — live Claude rationales

The rule-based scorer, batch job, evaluation, and UI all run **without** an API
key. To generate live Claude rationales instead of the rule-based fallback:

```bash
cp .env.example .env      # add your ANTHROPIC_API_KEY
python -m src.batch_classify --with-rationale
```

## Limitations & what's next

- **The dataset's labels are not learnable from its text.** Every accuracy figure
  above is bounded by that, and no amount of scorer tuning changes it. The
  evidence is in the Results section and in the console's own data-integrity
  panel.
- **The ticket bodies are templated** — 16 distinct subject lines across 8,469
  tickets, with a placeholder the source file never interpolated.
- **Average resolution time and volume-over-time are not reported anywhere**,
  because the timestamps cannot support them.
- Keyword lists are tuned to a generic IT-support vocabulary, not a real
  company's product taxonomy, which caps accuracy independently of the above.
- The dark-mode preference is scoped to the browser session and the URL; there is
  no server-side user preference store, because there is no user account system.
- **Next:** validate the scorer against a dataset whose labels correlate with its
  text — that is the only way to get a meaningful accuracy number, and it is a
  better use of time than tuning keywords against noise. Then run the live Claude
  rationale batch, tag `v1.0`, and deploy to Streamlit Community Cloud.

## Author

Built by Jeffrey De La Cruz as a portfolio project. See
[`CASE_STUDY.md`](CASE_STUDY.md) for the non-technical write-up.
