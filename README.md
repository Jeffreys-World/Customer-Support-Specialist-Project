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
5. A **Streamlit UI** shows the pre-sorted queue, per-ticket detail, and a
   confirm/adjust control that logs every agent override.

### The queue view

```
🔴 Critical  92  Payment failed on renewal, account locked out   Billing and Payments   ⚠️ breached  🛡️
🟠 High      71  Production API returning 500s for all users      Technical Support      3.1h left   🛡️
🟡 Medium    48  How do I export my report to PDF?                General Inquiry        18h left
🟢 Low       29  Feature request: dark mode would be nice         Product Support        60h left
```

## Results (measured, not estimated)

Evaluated on **11,923 English tickets** from the Kaggle multilingual
customer-support dataset, comparing the rule-based scorer to the dataset's own
`low`/`medium`/`high` ground-truth labels. The dataset has no "Critical" label,
so the product's four-level output is collapsed onto the dataset's three levels
(**Critical + High → `high`**) for an honest comparison. Full report:
[`results/evaluation.md`](results/evaluation.md).

| Metric | Value |
|---|---|
| **Top-severity (Critical-class) recall** — of `high` tickets, % flagged ≥ High | **49.2%** |
| Overall accuracy (3-way) | 41.6% |
| Recall — medium / low | 44.9% / 20.5% |
| Precision — high / medium | 46.8% / 44.6% |

Confusion matrix (truth ↓ / prediction →):

| | low | medium | high |
|---|---|---|---|
| **high** | 708 | 1,616 | 2,247 |
| **medium** | 945 | 2,222 | 1,785 |
| **low** | 493 | 1,141 | 766 |

**Reading the numbers honestly.** Priority in this generic dataset is only
weakly expressed through keywords, so a keyword scorer has a real ceiling — most
`high` tickets simply contain no urgency vocabulary. The calibration therefore
**optimizes recall on the top-severity class over overall accuracy** (a missed
critical ticket is Jordan's 4-hour incident; a false alarm is cheap), which is
why `high` precision is deliberately traded down. Where the system is *provably*
strong is the safety net: **every ticket containing a hard-priority signal is
guaranteed to escalate to at least High**, verified by parametrized tests
(`tests/test_rule_scorer.py`).

## Architecture

```
Ticket source (Kaggle CSV, simulating incoming tickets)
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

Python 3.9+ · pandas · Streamlit · Anthropic Python SDK (`claude-opus-4-8`,
structured JSON output) · python-dotenv · pytest.

## Setup & run

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 1. Build the English-only, priority-mapped working set from the raw Kaggle CSV
#    (place the CSV in data/raw/ first — see PROJECT_PLAN.md §5 for the dataset link)
python src/data_prep.py

# 2. Classify the batch (score-only; no API key needed)
python -m src.batch_classify

# 3. Launch the triage UI
streamlit run app.py

# 4. Reproduce the evaluation numbers
python -m src.evaluate

# 5. Run the test suite (safety net + UI smoke test)
pytest -q
```

### Optional — live Claude rationales

The rule-based scorer, batch job, evaluation, and UI all run **without** an API
key. To generate live Claude rationales instead of the rule-based fallback:

```bash
cp .env.example .env      # add your ANTHROPIC_API_KEY
python -m src.batch_classify --with-rationale
```

## Limitations & what's next

- **English-only** (German tickets are filtered out — a stated scope limit).
- Keyword lists are tuned to a generic IT-support dataset, not a real company's
  product taxonomy, which caps accuracy.
- **Next:** run the live Claude rationale batch and tag `v1.0`; add a lightweight
  trained classifier (TF-IDF + logistic regression) as a comparison baseline;
  deploy the Streamlit app to Streamlit Community Cloud for a clickable demo.

## Author

Built by Jeffrey De La Cruz as a portfolio project. See
[`CASE_STUDY.md`](CASE_STUDY.md) for the non-technical write-up.
