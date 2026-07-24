"""Tests for the rule-based scorer — with heavy emphasis on the Critical-class
safety net (PROJECT_PLAN.md §7), the single most important behaviour to protect.

A regression that lets a hard-trigger ticket slip below High is the worst possible
bug in this project, so those cases are exhaustive and explicit.
"""

from __future__ import annotations

import pytest

from src.rule_scorer import BASE_SCORE, HARD_TRIGGERS, score_many, score_ticket
from src.schema import Category, Ticket


def _score(body: str, subject: str = "") -> "ScoredTicket":  # noqa: F821
    return score_ticket(Ticket(id="t", subject=subject, body=body))


# --- Safety net: every hard trigger must force at least High -----------------

# One representative phrase per hard-trigger signal.
HARD_TRIGGER_PHRASES = {
    "outage": "We are experiencing a full service outage right now.",
    "system down": "The whole system went down and nobody can work.",
    "can't log in": "I can't log in to my account at all.",
    "security": "There is a serious security issue with my data.",
    "breach": "I think there was a data breach on my account.",
    "locked out": "I am completely locked out of the platform.",
    "payment failed": "My payment failed but I was still charged.",
    "service disruption": "We are experiencing significant downtime across the platform.",
    "data loss": "We have suffered data loss on the primary database.",
    "malware": "We detected malware on several machines.",
}


@pytest.mark.parametrize("signal,phrase", list(HARD_TRIGGER_PHRASES.items()))
def test_hard_trigger_forces_at_least_high(signal, phrase):
    scored = _score(phrase)
    assert scored.category.at_least(Category.HIGH), (
        f"hard trigger {signal!r} produced {scored.category.value} (score {scored.score})"
    )
    assert scored.safety_net_triggered is True


def test_every_hard_trigger_name_is_covered_by_a_test():
    # Guard against adding a trigger to the scorer without a corresponding test.
    assert set(HARD_TRIGGERS) == set(HARD_TRIGGER_PHRASES)


def test_safety_net_floors_a_low_scoring_ticket():
    # Minimal text with a single hard trigger scores below High on keywords alone,
    # so this proves the floor is doing the work — not incidental keyword mass.
    scored = _score("went down")
    assert scored.category is Category.HIGH
    assert scored.score >= 65
    assert scored.safety_net_triggered is True


def test_the_billing_incident_scenario_is_caught():
    # Jordan's 4-hour incident, re-run through the system (PROJECT_PLAN.md §10).
    scored = _score("Payment failed on renewal and my account is now locked out.")
    assert scored.category.at_least(Category.HIGH)
    assert scored.safety_net_triggered is True


# --- Non-triggering tickets must NOT be force-escalated ----------------------

def test_urgent_keyword_adds_weight_but_is_not_a_hard_trigger():
    scored = _score("This is urgent, please respond soon.")
    assert scored.safety_net_triggered is False  # "urgent" isn't a hard trigger
    assert scored.score > 15  # but it did add critical weight


def test_feature_request_stays_low():
    scored = _score("Feature request: it would be nice to have a dark mode.")
    assert scored.category is Category.LOW
    assert scored.safety_net_triggered is False


def test_plain_thank_you_is_not_escalated():
    scored = _score("Thank you for the great support last week!")
    assert scored.category in (Category.LOW, Category.MEDIUM)
    assert scored.safety_net_triggered is False


# --- Scoring mechanics -------------------------------------------------------

def test_score_is_clamped_to_0_100():
    scored = _score(
        "Outage! Security breach! Payment failed! Account locked out! Urgent emergency!"
    )
    assert 0 <= scored.score <= 100
    assert scored.category is Category.CRITICAL  # heavy accumulation reaches Critical


def test_category_boundaries_from_score():
    assert Category.from_score(90) is Category.CRITICAL
    assert Category.from_score(89) is Category.HIGH
    assert Category.from_score(65) is Category.HIGH
    assert Category.from_score(64) is Category.MEDIUM
    assert Category.from_score(35) is Category.MEDIUM
    assert Category.from_score(34) is Category.LOW
    assert Category.from_score(0) is Category.LOW


def test_matched_signals_are_recorded():
    scored = _score("The billing invoice shows an error and the app is slow.")
    assert scored.matched_signals  # non-empty
    assert "error" in scored.matched_signals


# --- Severity vocabulary (recall expansion) ----------------------------------

# One representative phrase per newly added high-severity signal group. Each must
# add weight above the neutral base and record its signal name.
SEVERITY_PHRASES = {
    "impact": "The bug is affecting every customer on the platform.",
    "incident": "We are managing an active incident right now.",
    "unexpected": "The service went down unexpectedly this morning.",
    "failure": "There is a complete failure of the export module.",
    "unresponsive": "The dashboard is unresponsive and will not load.",
    "inaccessible": "The reporting page is completely inaccessible.",
    "blocked": "Our whole team is at a standstill and cannot work.",
}


@pytest.mark.parametrize("signal,phrase", list(SEVERITY_PHRASES.items()))
def test_severity_vocabulary_adds_weight(signal, phrase):
    scored = _score(phrase)
    assert scored.score > BASE_SCORE, f"{signal!r} added no weight (score {scored.score})"
    assert signal in scored.matched_signals


def test_compound_severity_ticket_reaches_high():
    # Two independent severity signals should clear the High threshold on keyword
    # mass alone — no safety-net floor involved.
    scored = _score("Unexpected system failure — the platform is unresponsive for all users.")
    assert scored.category.at_least(Category.HIGH)
    assert scored.safety_net_triggered is False


def test_vulnerability_is_a_hard_trigger():
    # "vulnerability"/"vulnerabilities" were added to the security hard trigger.
    scored = _score("We discovered several vulnerabilities in the login flow.")
    assert scored.category.at_least(Category.HIGH)
    assert scored.safety_net_triggered is True


def test_repeat_contact_adds_weight():
    once = _score("The report export is not working.")
    again = _score("The report export is still not working, as I mentioned before.")
    assert again.score > once.score
    assert "repeat-contact" in again.matched_signals


def test_scoring_is_deterministic():
    body = "Security breach and payment failed, please help urgently."
    assert score_ticket(Ticket(id="a", subject="", body=body)).score == \
        score_ticket(Ticket(id="a", subject="", body=body)).score


def test_score_many_sorts_most_urgent_first():
    tickets = [
        Ticket(id="low", subject="", body="Feature request: dark mode would be nice."),
        Ticket(id="crit", subject="", body="Full outage, security breach, payment failed, urgent!"),
        Ticket(id="med", subject="", body="The dashboard is slow and I have a question."),
    ]
    ordered = score_many(tickets)
    ranks = [s.category.rank for s in ordered]
    assert ranks == sorted(ranks, reverse=True)
    assert ordered[0].ticket.id == "crit"
