"""Stage 2 — the rule-based priority scorer and its Critical-class safety net.

This is the most important module in the project. It turns a ticket's text into a
deterministic 0–100 urgency score, a category, and the list of signals that fired.
The LLM layer later *explains* this score; it never overrides it (PROJECT_PLAN.md §3).

## Scoring model
A neutral baseline plus weighted keyword hits, capped to 0–100. Keyword sets and
weights were tuned against the real dataset (see results/evaluation.md), which
showed top-severity tickets cluster on infrastructure/outage/crash/security
vocabulary:

    base 28
    + 30  per critical signal   (outage, breach, payment failed, "urgent", …)
    + 24  per high signal       (crash, error, server/capacity, billing, …)
    + 10  per medium signal     (question, "how do I", slow, configure, …)
    +  1  per low signal         (feature request, documentation, feedback)
    + 10  once, if the customer signals a repeat/escalating contact ("again", "still")

The calibration deliberately favours **recall on the top-severity class over
overall accuracy** (PROJECT_PLAN.md §7, §10): a lone hard-trigger keyword lands
below the High threshold on keyword mass alone, and the safety net below lifts it.

## Critical-class safety net (PROJECT_PLAN.md §7 — the #1 correctness rule)
The costliest failure is a genuinely critical ticket read as routine — exactly Jordan's
4-hour billing incident. So any ticket containing a *hard-trigger* signal (outage, down,
can't log in, security, breach, locked out, payment failed) is force-escalated to at
least High regardless of its numeric score. We optimise for recall on the top-severity
class first and overall accuracy second: over-firing to High is an acceptable cost, a
missed critical ticket is not.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from src.schema import Category, ScoredTicket, Ticket

# --- Weights -----------------------------------------------------------------
BASE_SCORE = 28
CRITICAL_WEIGHT = 30
HIGH_WEIGHT = 24
MEDIUM_WEIGHT = 10
LOW_WEIGHT = 1
REPEAT_WEIGHT = 10

# --- Signal definitions ------------------------------------------------------
# Each signal maps a human-readable name -> surface variants matched case-insensitively.
# Phrases are preferred over bare words where a bare word would be noisy. Sets were
# expanded from a term-frequency analysis of the real dataset by priority label.

# Hard triggers: presence forces the category to at least High (the safety net).
HARD_TRIGGERS: Dict[str, List[str]] = {
    "outage": ["outage", "outages"],
    "system down": [
        "is down", "are down", "system down", "server down", "servers down",
        "site down", "website down", "service is down", "service down",
        "everything is down", "went down", "completely down", "totally down", " down ",
    ],
    "can't log in": [
        "can't log in", "cant log in", "can not log in", "cannot log in",
        "can't login", "cannot login", "unable to log in", "unable to login",
        "can't access my account", "cannot access my account", "cannot access", "can't access",
    ],
    "security": ["security breach", "security issue", "security vulnerability", "security",
                 "vulnerability", "vulnerabilities"],
    "breach": ["breach", "breached", "data breach", "hacked", "compromised account"],
    "locked out": ["locked out", "lock out", "account locked", "account is locked"],
    "payment failed": [
        "payment failed", "payment declined", "failed payment", "charge failed",
        "transaction failed", "double charged", "charged twice", "unauthorized charge",
        "unauthorised charge",
    ],
    "service disruption": [
        "downtime", "disruption", "disrupting", "interruption", "not operational",
        "unavailable", "service is unavailable",
    ],
    "data loss": ["data loss", "lost all", "losing data", "lost my data", "lost our data"],
    "malware": ["phishing", "malware", "ransomware", "suspicious login", "suspicious activity"],
}

# Extra critical-weight signals that do NOT force escalation on their own.
CRITICAL_EXTRA: Dict[str, List[str]] = {
    "urgent": ["urgent", "urgently", "asap", "emergency", "immediately", "immediate",
               "time-sensitive", "time sensitive", "critical", "escalate", "escalation"],
}

HIGH_SIGNALS: Dict[str, List[str]] = {
    "broken": ["broken", "broke"],
    "not working": ["not working", "doesn't work", "does not work", "won't work",
                    "stopped working", "no longer works"],
    "error": ["error", "errors", "exception", "crash", "crashed", "crashes", "crashing",
              "failing", "fails"],
    "billing issue": ["billing issue", "billing problem", "invoice", "invoices",
                      "overcharged", "wrong charge", "refund"],
    "infrastructure": ["server", "servers", "node", "cluster", "capacity", "overloaded",
                       "overload", "firewall", "out of memory", "memory pressure", "high load",
                       "degraded", "latency", "impacted", "impacting", "production", "restore",
                       "operational"],
    "multiple users": ["multiple users", "several users", "many users", "all users",
                       "whole team", "entire team"],
    # Severity/impact vocabulary expanded from a term-frequency analysis of the real
    # dataset (results/evaluation.md): these words are strongly over-represented in
    # top-severity tickets whose urgency isn't stated with an explicit priority word.
    "impact": ["affected", "affecting", "widespread", "system-wide", "company-wide",
               "across the board"],
    "incident": ["incident", "incidents"],
    "unexpected": ["unexpected", "unexpectedly", "suddenly", "abruptly", "out of nowhere"],
    "failure": ["failure", "failures", "malfunction", "malfunctioning", "malfunctions",
                "not functioning", "non-functional"],
    "unresponsive": ["unresponsive", "not responding", "frozen", "freezes", "freezing",
                     "hangs", "hanging", "timeout", "timed out", "times out", "timing out"],
    "inaccessible": ["inaccessible", "unusable", "cannot use", "can't use", "no longer able"],
    "blocked": ["blocker", "blocking us", "at a standstill", "grinding to a halt",
                "brought to a halt", "halted"],
}

MEDIUM_SIGNALS: Dict[str, List[str]] = {
    "question": ["question", "questions", "clarify", "clarification", "inquiry"],
    "how do I": ["how do i", "how can i", "how to", "where do i", "is it possible"],
    "slow": ["slow", "slowly", "sluggish", "lagging", "delayed", "taking too long"],
    "config/admin": ["configure", "setup", "set up", "integration", "permissions",
                     "subscription", "tracking", "report", "update", "access", "enable"],
}

LOW_SIGNALS: Dict[str, List[str]] = {
    "feature request": ["feature request", "feature suggestion", "would be nice",
                        "it would be great if", "suggestion", "enhancement"],
    "documentation": ["documentation", "docs", "user guide", "manual", "how-to guide", "tutorial"],
    "feedback": ["feedback", "just wanted to say", "thank you", "compliment"],
    "minor/cosmetic": ["browser", "cache", "clearing cache", "cosmetic", "typo", "display issue"],
}

REPEAT_SIGNALS: List[str] = [
    "again", "still not", "still doesn't", "still does not", "as i mentioned",
    "as mentioned", "as stated", "third time", "second time", "multiple times",
    "several times", "keeps happening", "keep happening", "reopen", "follow up",
    "following up", "no response",
]


def _find_matches(text: str, signals: Dict[str, List[str]]) -> List[str]:
    """Return the names of every signal whose any variant appears in ``text``."""
    return [name for name, variants in signals.items() if any(v in text for v in variants)]


def score_ticket(ticket: Ticket) -> ScoredTicket:
    """Score one ticket. Deterministic — same input always yields the same output."""
    text = ticket.text.lower()
    matched: List[str] = []
    score = BASE_SCORE

    hard_hits = _find_matches(text, HARD_TRIGGERS)
    for name in hard_hits:
        score += CRITICAL_WEIGHT
    matched.extend(hard_hits)

    for name in _find_matches(text, CRITICAL_EXTRA):
        score += CRITICAL_WEIGHT
        matched.append(name)

    for name in _find_matches(text, HIGH_SIGNALS):
        score += HIGH_WEIGHT
        matched.append(name)

    for name in _find_matches(text, MEDIUM_SIGNALS):
        score += MEDIUM_WEIGHT
        matched.append(name)

    for name in _find_matches(text, LOW_SIGNALS):
        score += LOW_WEIGHT
        matched.append(name)

    if any(sig in text for sig in REPEAT_SIGNALS):
        score += REPEAT_WEIGHT
        matched.append("repeat-contact")

    score = max(0, min(100, score))
    category = Category.from_score(score)

    # --- Critical-class safety net (the #1 rule) -----------------------------
    safety_net_triggered = bool(hard_hits)
    if safety_net_triggered and not category.at_least(Category.HIGH):
        category = Category.HIGH
        score = max(score, 65)

    return ScoredTicket(
        ticket=ticket,
        score=score,
        category=category,
        matched_signals=matched,
        safety_net_triggered=safety_net_triggered,
    )


def score_many(tickets: List[Ticket]) -> List[ScoredTicket]:
    """Score a batch of tickets, most-urgent first."""
    scored = [score_ticket(t) for t in tickets]
    scored.sort(key=lambda s: (s.category.rank, s.score), reverse=True)
    return scored


def explain(scored: ScoredTicket) -> Tuple[int, str, List[str]]:
    """Small helper for quick CLI/debug output: (score, category value, signals)."""
    return scored.score, scored.category.value, scored.matched_signals


if __name__ == "__main__":
    # Smoke test on a handful of representative tickets (PROJECT_PLAN.md §8, days 3–4:
    # "running it on ~20 sample tickets produces sensible scores/categories").
    samples = [
        ("Payment failed and I was double charged", "urgent billing"),
        ("Entire team locked out — system down since this morning", "outage"),
        ("Security breach: I think my account was hacked", "security"),
        ("How do I export my report to PDF?", "how-to"),
        ("Feature request: dark mode would be nice", "low"),
        ("The dashboard is slow when loading large datasets", "medium"),
        ("Login error again, still not working after your last fix", "repeat"),
        ("Thank you for the great support last week!", "feedback"),
    ]
    for body, label in samples:
        s = score_ticket(Ticket(id="demo", subject="", body=body))
        flag = "  [SAFETY NET]" if s.safety_net_triggered else ""
        print(f"{s.category.emoji} {s.category.value:<8} {s.score:>3}  ({label}){flag}")
        print(f"      signals: {', '.join(s.matched_signals) or '—'}")
