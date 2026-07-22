# Evaluation — Jordan's Ticket Triage Assistant

Rule-based scorer vs. dataset ground-truth priority labels, over **11,923 English tickets**. Ground truth is the dataset's own `low`/`medium`/`high` label — no relabelling. The scorer's four-level output (Critical/High/Medium/Low) is collapsed to the dataset's three levels for comparison: **Critical + High → `high`**.

## 1. Top-severity (Critical-class) recall — the headline metric

Of the **4,571** tickets the dataset labels `high`, the scorer flagged **1,836** as Critical or High.

> **Top-severity recall = 40.2%**

This is the number that matters most: a `high` ticket read as routine is exactly Jordan's 4-hour billing incident.

## 2. Overall accuracy & confusion matrix

**Overall accuracy: 40.6%** (4,838/11,923 correct).

Rows = dataset label (truth), columns = scorer prediction (collapsed).

| truth ↓ / pred → | low | medium | high | recall |
|---|---|---|---|---|
| **high** | 802 | 1,933 | 1,836 | 40.2% |
| **medium** | 1,038 | 2,458 | 1,456 | 49.6% |
| **low** | 544 | 1,241 | 615 | 22.7% |
| **precision** | 22.8% | 43.6% | 47.0% | |

## 3. Where the 🔴 Critical predictions land

The scorer assigned 🔴 Critical to **1,658** tickets. Against the dataset label they split: **880 high**, 575 medium, 203 low. (All of these count as correct top-severity, since Critical → `high`.)

## 4. Systematic confusions & examples

The scorer is keyword-driven, so tickets whose urgency isn't expressed with priority keywords fall to Low — the main driver of missed `high`/`medium` recall. Representative misses:

- **high → Low**: “Boost Data Analytics Support” (score 30)
- **high → Low**: “Identifying Issues with Campaign Engagement” (score 28)
- **high → Low**: “Enhancement Strategies” (score 29)

## 5. Manual spot-check

A 25-ticket sample is written to `results/spot_check_sample.csv` for a human reviewer to mark agree/disagree (PROJECT_PLAN.md §10). This is a small-sample sanity check, not a statistically powered metric, and the human agreement rate is intentionally left blank until reviewed — no fabricated numbers.

## 6. Honest limitations

- **English-only** coverage (German tickets filtered out).
- Keyword lists are tuned to a generic IT-support dataset, not a real company's product taxonomy — the ceiling on accuracy is low by design.
- The safety net optimises **recall on the top-severity class first**; it over-fires to High on some routine tickets, which lowers `high` precision. That trade is deliberate: a missed critical ticket costs far more than a false alarm.
