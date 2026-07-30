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
analysis. It reports four measured findings:

- the priority label is independent of the ticket text (chi-square, live);
- the timestamps do not describe a timeline, so two charts were cut;
- **every blank field is explained by `status` alone** — `first_response_at`,
  `resolved_at`, `resolution` and `csat` each match their status rule with zero
  exceptions, which is why there is no "awaiting response" urgency flag and no
  overdue metric (the dataset has no ticket-creation timestamp at all);
- **the resolution notes are generator filler** — 2,769 notes, all unique, only 120
  using any support vocabulary, 0 naming the product they supposedly fixed.

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
| Resolution state (whether a closing note was recorded) | |
| Your confirm/override decisions, and the agreement statistics computed from them | |

Nothing in the simulated column influences triage.

One column is deliberately **withheld** rather than shown or simulated: the dataset's
`Resolution` note text. It is carried through the pipeline so that the integrity panel
can measure it, but it reads like *"Case maybe show recently my computer follow."*
The ticket workspace therefore shows resolution *state* rather than passing filler off
as an agent's closing note — the same call the pipeline already makes about the
unfilled `{product_purchased}` token in the raw bodies.

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

**That claim, tested directly.** Rather than leave "no classifier could do better"
as an inference from chi-square, it was measured. `python -m prediction_model` trains
three models of increasing strength against the same label, with a seeded 80/20
split. Full report: [`results/priority_prediction.md`](results/priority_prediction.md).

| Feature set | Held-out accuracy | 5-fold CV | Train accuracy | Gap |
|---|---|---|---|---|
| The two features a plan proposed (urgency score + days since purchase) | **24.9%** | 26.4% | 70.1% | +45.2 pts |
| Every operational column, one-hot encoded (59 features) | **25.9%** | 26.6% | 85.2% | +59.3 pts |
| The ticket text itself (TF-IDF, 1–2 grams) | **26.1%** | 25.9% | 62.2% | +36.1 pts |

Chance is 25.0% and always-guess-the-majority-class is 25.9%. The best model beats
that baseline by 0.2 points on 1,694 held-out rows, where one standard error is 1.1
points — so it is noise, and the report applies that two-standard-error test rather
than comparing raw percentages. The text model is the one that matters: if the label
were recoverable from anything this dataset carries, TF-IDF over the subject and body
would have found it.

The **train accuracy** column is the other half of the lesson. Fit and score on the
same rows and the first model reports 70.1%, which is what a plan for this feature
originally specified. Every feature set shows a 36–59 point memorisation gap. No
`Predicted_Priority` column was added to the console: at these numbers it would be a
random column sitting beside a real one.

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

Off to one side, importing none of the above and imported by none of it:
prediction_model.py ──► results/priority_prediction.md  (the ML ceiling experiment)
```

The scorer and the LLM are deliberately separate (PROJECT_PLAN.md §3): the score
must be reliable and cheap to run on 200–300 tickets; the LLM only explains it.
If the API key is missing or a call fails, the batch job degrades to a
deterministic rule-based rationale — the queue still sorts correctly. No single
point of failure.

## Tech stack

Python 3.9+ · pandas · Streamlit · Altair · Anthropic Python SDK
(`claude-opus-4-8`, structured JSON output) · python-dotenv · pytest.
scikit-learn is a dev-only dependency, used solely by `prediction_model.py`; the
console never imports it, so the app runs without it installed.

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

# 5. Reproduce the ML ceiling experiment (--write updates the report)
python -m prediction_model

# 6. Run the test suite (safety net + UI smoke test)
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
  above is bounded by that, and no amount of scorer tuning changes it. Nor is it a
  scorer problem: three ML models, up to TF-IDF over the raw text, all land inside
  noise of the majority-class baseline
  ([`results/priority_prediction.md`](results/priority_prediction.md)).
- **The ticket bodies are templated** — 16 distinct subject lines across 8,469
  tickets, with a placeholder the source file never interpolated. The `Resolution`
  notes are filler too, which is why their text is not displayed.
- **Average resolution time and volume-over-time are not reported anywhere**,
  because the timestamps cannot support them.
- **No days-open, overdue, or SLA-from-timestamps metric exists**, because the
  dataset has no ticket-creation timestamp — only a purchase date preceding every
  ticket by years. The queue's SLA countdown is a hash-derived demo clock and is
  labelled as such. Every partially-filled field's blanks are fully explained by
  `status`, so no completeness flag adds information beyond it.
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
