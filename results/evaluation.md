# Evaluation — Jordan's Ticket Triage Assistant

Rule-based scorer vs. dataset ground-truth priority labels, over **11,923 English tickets**. Ground truth is the dataset's own `low`/`medium`/`high` label — no relabelling. The scorer's four-level output (Critical/High/Medium/Low) is collapsed to the dataset's three levels for comparison: **Critical + High → `high`**.

## 1. Top-severity (Critical-class) recall — the headline metric

Of the **4,571** tickets the dataset labels `high`, the scorer flagged **2,247** as Critical or High.

> **Top-severity recall = 49.2%**

This is the number that matters most: a `high` ticket read as routine is exactly Jordan's 4-hour billing incident.

## 2. Overall accuracy & confusion matrix

**Overall accuracy: 41.6%** (4,962/11,923 correct).

Rows = dataset label (truth), columns = scorer prediction (collapsed).

| truth ↓ / pred → | low | medium | high | recall |
|---|---|---|---|---|
| **high** | 708 | 1,616 | 2,247 | 49.2% |
| **medium** | 945 | 2,222 | 1,785 | 44.9% |
| **low** | 493 | 1,141 | 766 | 20.5% |
| **precision** | 23.0% | 44.6% | 46.8% | |

## 3. Where the 🔴 Critical predictions land

The scorer assigned 🔴 Critical to **2,566** tickets. Against the dataset label they split: **1,348 high**, 897 medium, 321 low. (All of these count as correct top-severity, since Critical → `high`.)

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
