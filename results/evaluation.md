# Evaluation — Jordan's Ticket Triage Assistant

Rule-based scorer vs. dataset ground-truth priority labels, over **8,469 tickets** from `customer_support_tickets.csv`. Ground truth is the dataset's own four-level `Ticket Priority` label — no relabelling, no collapsing. The scorer's output scale and the dataset's label scale are now identical, so a Critical prediction is scored against a real Critical label.

> **Headline: the scorer performs at chance on this dataset, and that is a property of the dataset, not a bug in the scorer.** Section 3 shows the label is statistically independent of the ticket text. Section 1 and 2 should be read in that light.

## 1. Critical-class recall — the headline metric

Of the **2,129** tickets the dataset labels `Critical`, the scorer flagged **605** as Critical or High.

> **Critical-class recall = 28.4%**

Over the wider top-severity bucket (`Critical` + `High`, 4,214 tickets) recall is **28.8%**.

The number to compare these against: the scorer calls **27.9%** of *all* tickets top-severity. Recall that matches the flag rate is what you get from flagging tickets at random — the scorer is not finding critical tickets, it is finding its own keywords, which this dataset scatters independently of the label.

## 2. Overall accuracy & confusion matrix

**Overall accuracy: 26.0%** (2,204/8,469 correct) against a **25.0% chance baseline** and a 25.9% majority-class baseline.

Rows = dataset label (truth), columns = scorer prediction.

| truth ↓ / pred → | Critical | High | Medium | Low | recall |
|---|---|---|---|---|---|
| **Critical** | 173 | 432 | 1,067 | 457 | 8.1% |
| **High** | 170 | 437 | 1,050 | 428 | 21.0% |
| **Medium** | 158 | 419 | 1,140 | 475 | 52.0% |
| **Low** | 147 | 427 | 1,035 | 454 | 22.0% |
| **precision** | 26.7% | 25.5% | 26.6% | 25.0% | |

Two notes on reading this table. The `recall` column is **exact-match** recall (the diagonal), which is why Critical reads 8.1% here while section 1 reports 28.4% — that headline counts a Critical ticket caught as *either* Critical or High, which is the operationally relevant question. And Medium's apparently strong recall is an artifact of central tendency, not skill: the scorer puts a plurality of everything in Medium, so it wins that row by answering the same way every time.

Read the rows, not the diagonal. Every row is close to identical: the scorer emits nearly the same distribution of predictions whether the ticket is truly Critical or truly Low. That shape — not the accuracy figure — is the actual finding.

## 3. Is the label predictable at all?

Two chi-square tests of independence. Cramér's V is the effect size: 0 means no relationship, 1 means one variable determines the other. At n=8,469 a p-value alone would be misleading, so read V.

| Test | chi² | dof | p | Cramér's V |
|---|---|---|---|---|
| Scorer prediction × true label | 7.0 | 9 | 0.642 | **0.017** |
| Ticket subject × true label | 40.9 | 45 | 0.648 | **0.040** |

Both chi² statistics sit at or below their degrees of freedom, which is what pure independence looks like — under the null hypothesis the expected value of chi² *is* dof.

The second row is the important one. It does not involve this scorer at all: it asks whether the ticket's own subject line predicts its priority. It does not. **No classifier reading this text could do better, because the text and the label were generated independently.** The dataset ships 16 distinct subject lines and a template body whose product placeholder was never even interpolated (see `src/data_prep.py`).

## 4. Where the Critical predictions land

The scorer assigned Critical to **648** tickets. Against the dataset label they split: **173 Critical**, **170 High**, **158 Medium**, **147 Low**. An even split across four labels is, again, independence.

## 5. The safety net still works

The Critical-class safety net fired on **1,525** tickets (18.0% of the batch), forcing every hard-trigger ticket (outage, breach, locked out, payment failed, …) to at least High regardless of its numeric score.

This is worth stating plainly because the chance-level accuracy above invites the wrong conclusion. The safety net is a **deterministic guarantee about vocabulary**, not a prediction: any ticket containing a hard trigger is escalated, and `tests/test_rule_scorer.py` asserts that exhaustively. What this dataset removes is the ability to *measure* whether escalation correlates with the label, because the label correlates with nothing. The mechanism is intact; the measuring stick is broken.

## 6. Systematic confusions & examples

With an independent label there is no systematic confusion to describe — misses are not concentrated in any category of ticket. Representative examples of `Critical` truth scored `Low`:

- **Critical → Low**: “Battery life” (score 28)
- **Critical → Low**: “Installation support” (score 28)
- **Critical → Low**: “Product recommendation” (score 29)

## 7. Manual spot-check

A 25-ticket sample is written to `results/spot_check_sample.csv` for a human reviewer to mark agree/disagree (PROJECT_PLAN.md §10). This is a small-sample sanity check, not a statistically powered metric, and the human agreement rate is intentionally left blank until reviewed — no fabricated numbers.

On this dataset the spot-check is the *more* informative artifact: a human reading the ticket text can judge whether the scorer's call is sensible, which the dataset's own label cannot.

## 8. Honest limitations

- **The dataset's labels are not learnable from its text.** Everything in sections 1, 2 and 4 is bounded by that. Accuracy here measures the data, not the model.
- **The ticket bodies are templated.** 16 unique subject lines across 8,469 tickets, and the raw descriptions ship with an unfilled `{product_purchased}` token that `data_prep` substitutes.
- **Resolution-time and trend metrics are not reported anywhere in this project**, because 49.3% of closed tickets carry a resolution timestamp earlier than their first-response timestamp, and every timestamp falls inside a single 3-day window. See the Dashboard's data-integrity panel.
- Keyword lists are tuned to a generic IT-support vocabulary, not a real company's product taxonomy — the ceiling on accuracy is low by design.
- The safety net optimises **recall on the top-severity class first**; it over-fires to High on some routine tickets, which lowers precision. That trade is deliberate: a missed critical ticket costs far more than a false alarm.
