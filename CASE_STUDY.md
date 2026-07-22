# Case study — Jordan's Ticket Triage Assistant

## The hook

Jordan handles 200–300 support tickets a week. Every morning starts the same
way: an unsorted queue, and roughly 90 minutes spent reading and re-ordering it
by hand before any real work begins. The cost isn't just the time — one week a
customer's payment-failure ticket sat unopened for four hours because nothing in
the queue made it stand out. By the time Jordan reached it, the customer had
already escalated.

## The process — finding the real problem

I started with five whys, not with code:

1. *Why did the critical ticket sit for four hours?* It wasn't visible near the
   top of the queue.
2. *Why wasn't it near the top?* The queue isn't sorted by urgency.
3. *Why isn't it sorted?* Sorting is manual, and Jordan can't read 250 tickets
   before starting.
4. *Why is it manual?* There's no automated triage step.
5. *Why is there no automation?* The company already has years of labeled
   support data — it just isn't being used to prioritize incoming tickets.

The root cause wasn't Jordan working too slowly. It was a missing triage layer.
That reframed the whole project: don't build a faster agent, build the sorted
queue the agent should have been opening all along.

## What I built

An automated triage layer that scores and sorts every ticket **before** Jordan
opens the queue, and explains each decision in plain language:

- a deterministic scorer that assigns a 0–100 urgency score and a priority;
- a **safety net** that guarantees any ticket mentioning an outage, a breach, a
  failed payment, or a locked-out account is escalated — the exact failure mode
  behind the 4-hour incident;
- a short Claude-written rationale and a suggested queue for each ticket;
- a Streamlit dashboard where Jordan sees the pre-sorted queue, reads the "why,"
  and can confirm or override — the system recommends, Jordan decides.

## The impact

On 11,923 real tickets, the scorer catches **40% of all high-priority tickets**
from keyword signals alone on a generic dataset, and — more importantly —
**provably escalates 100% of tickets that contain a hard-priority signal**, which
is the case that burned Jordan. Time-to-sorted-queue drops from ~90 minutes of
manual reading to instant. The billing-ticket scenario, re-run through the
system, is now flagged Critical automatically.

I was deliberate about reporting these numbers honestly: priority in a generic
dataset is only weakly expressed in words, so I tuned for *recall on the urgent
class over headline accuracy* — because missing a critical ticket costs far more
than a false alarm — and documented that trade-off rather than hiding it.

## What I'd do differently / next

- Tune the keyword taxonomy to a real company's product vocabulary, where
  urgency language is far more consistent than in a generic dataset.
- Add a small trained classifier (TF-IDF + logistic regression) as a comparison
  baseline against the rule-based scorer.
- Deploy the dashboard so a hiring manager can click through it, not just read
  about it.

## Links

- Code, architecture, and full results: [`README.md`](README.md)
- Measured evaluation: [`results/evaluation.md`](results/evaluation.md)
