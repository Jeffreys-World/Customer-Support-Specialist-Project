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

Time-to-sorted-queue drops from ~90 minutes of manual reading to instant, and the
safety net **provably escalates 100% of tickets containing a hard-priority
signal** — the exact case that burned Jordan. That guarantee is verified by
parametrized tests, not estimated. The billing-ticket scenario, re-run through the
system, is flagged Critical automatically.

## The part I did not expect

Partway through, I swapped in a richer dataset so the dashboard could show ticket
status, channel, and satisfaction — columns the original data simply didn't have.
Before trusting it, I profiled it. The priority labels turned out to be
**statistically independent of the ticket text**: chi-square at or below its
degrees of freedom for every text-versus-label pair, Cramér's V of 0.04, only 16
distinct subject lines across 8,469 tickets, and a template placeholder the
source file had never filled in. Half the "closed" tickets recorded a resolution
timestamp *earlier* than their first response.

So the scorer that had measured 49% recall on the old data now measured 26%
accuracy against a 25% chance baseline. The confusion matrix said it more clearly
than any statistic: all four rows were nearly identical, meaning the scorer
predicted the same thing whether a ticket was truly Critical or truly Low.

I had two options. Report the lower number quietly, or report what the number
actually meant. I did the second: the console now carries a "Data integrity"
panel that states the labels are unlearnable, shows the chi-square evidence, and
explains why two charts the brief asked for — average resolution time and volume
over time — are **not on the dashboard at all**. They were cut rather than faked.

That decision cost the project its best-looking headline metric. I think it is
the most valuable thing in the repo. Anyone can produce a number. Knowing when a
number is meaningless, proving it, and saying so in the product is the harder
skill and the one that actually protects a business from acting on noise.

## Testing my own claim

"The labels are unlearnable" is a strong thing to assert from a chi-square, and the
obvious objection is that a real machine-learning model might find signal a keyword
scorer misses. So I tried to prove myself wrong: three models against the same label,
each stronger than the last — two hand-picked features, then all 59 operational
columns one-hot encoded, then TF-IDF over the ticket text itself.

Held-out accuracy: 24.9%, 25.9%, 26.1%. Chance is 25.0% and always-guessing-the-
biggest-class is 25.9%. The best model beats that by 0.2 points on 1,694 tickets,
where one standard error is 1.1 points — so it is noise, and I report it as noise
rather than as a win.

The more useful number is the one beside it. Fit and score those models on the same
rows, and the first reports **70.1%**. That is the figure a plan for this feature
originally specified, and it is pure memorisation: a 45-point gap to its real
performance. There is no predicted-priority column in the console, because at 25%
it would be a random number sitting next to a real one.

Two smaller findings came out of the same profiling pass. The `Resolution` column
looked like a gift — 2,769 free-text closing notes going unused — until I read them:
*"Case maybe show recently my computer follow."* All unique, 4% containing any
support word, none naming the product they supposedly fixed. And the three
data-quality flags I had planned turned out to be the `status` column wearing a
different hat: every blank field's blanks are perfectly predicted by status, and
there is no ticket-creation timestamp anywhere, so "open more than 5 days" was true
for all 8,469 rows. I shipped the measurement instead of the flags.

## What I'd do differently / next

- **Validate against a dataset whose labels correlate with its text.** That is the
  only way to get a meaningful accuracy figure, and it beats tuning keywords
  against noise.
- Profile label quality *before* building on a dataset, not after. Ten minutes of
  chi-square would have reframed the swap up front. The same goes for individual
  columns: I planned three features around `Resolution` and a days-open clock before
  checking that one was filler and the other did not exist.
- The TF-IDF classifier is now built, but as a ceiling test rather than a baseline.
  On data where learning *is* possible, the same file becomes the comparison the
  rule-based scorer is measured against — that is the interesting version of it.
- Deploy the dashboard so a hiring manager can click through it, not just read
  about it.

## Links

- Code, architecture, and full results: [`README.md`](README.md)
- Measured evaluation: [`results/evaluation.md`](results/evaluation.md)
- The ML ceiling experiment: [`results/priority_prediction.md`](results/priority_prediction.md)
