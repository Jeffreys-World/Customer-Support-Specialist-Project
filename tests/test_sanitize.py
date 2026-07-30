"""Tests for the model boundary (`src.sanitize`).

The behaviour worth protecting here is a negative one: identity must not reach
an external model. A leak is silent — the pipeline still runs, the rationales
still come back, and nothing looks wrong — so it needs tests that fail loudly
rather than a code comment asking future contributors to be careful.

The last test is the one that matters. Everything above it checks a helper in
isolation; `test_built_prompt_carries_no_identity` checks the actual string that
would be posted to the API.
"""

from __future__ import annotations

import pytest

from src.llm_rationale import _build_user_prompt
from src.rule_scorer import score_ticket
from src.sanitize import (
    SAFE_TICKET_FIELDS,
    redact_text,
    sanitize_records,
    sanitize_scored_ticket,
)
from src.schema import Ticket

# A ticket carrying identity in BOTH places it can hide: dedicated columns, and
# inline in the prose the model is supposed to read.
IDENTIFYING_TICKET = Ticket(
    id="T00001",
    subject="Payment failed for Sarah Chen",
    body=(
        "My payment failed. Reach me at sarah.chen@example.com or 555-867-5309. "
        "The card ending 4111 1111 1111 1111 was charged anyway."
    ),
    requester_name="Sarah Chen",
    requester_email="sarah.chen@example.com",
    purchase_date="2024-03-02",
    csat="4",
)


# --- Allowlist ----------------------------------------------------------------

def test_allowlist_keeps_only_named_fields():
    [clean] = sanitize_records([IDENTIFYING_TICKET])
    assert set(clean) == set(SAFE_TICKET_FIELDS)


@pytest.mark.parametrize("withheld", ["requester_name", "requester_email",
                                      "purchase_date", "csat", "id"])
def test_allowlist_withholds_identity_and_operational_columns(withheld):
    [clean] = sanitize_records([IDENTIFYING_TICKET])
    assert withheld not in clean


def test_unknown_fields_are_dropped_not_passed_through():
    """A column nobody anticipated must not ride along. This is the whole reason
    the module allowlists instead of denylisting."""
    [clean] = sanitize_records([{"subject": "hi", "body": "there",
                                 "national_id": "X", "home_address": "Y"}])
    assert clean == {"subject": "hi", "body": "there"}


def test_missing_allowlisted_field_is_omitted_not_defaulted():
    """`field in mapping` guards the read, so a partial record yields a partial
    dict rather than a KeyError or a fabricated empty value."""
    [clean] = sanitize_records([{"subject": "only a subject"}])
    assert clean == {"subject": "only a subject"}


def test_caller_supplied_allowlist_is_respected():
    [clean] = sanitize_records([IDENTIFYING_TICKET], ["subject"])
    assert set(clean) == {"subject"}
    # Narrowing the allowlist must not switch redaction off for what remains.
    assert clean["subject"] == "Payment failed for [redacted:name]"


def test_returns_plain_dicts_not_the_original_objects():
    """A caller must not be handed a reference it can read withheld fields
    through."""
    [clean] = sanitize_records([IDENTIFYING_TICKET])
    assert isinstance(clean, dict)
    assert not hasattr(clean, "requester_email")


@pytest.mark.parametrize("bad", [None, 42, "a string", {"subject": "a mapping"}])
def test_non_list_input_yields_empty_rather_than_raising(bad):
    """This sits on the path to an external API. The safe failure is an empty
    payload; a traceback invites a caller to fall back to the raw records."""
    assert sanitize_records(bad) == []


def test_unreadable_records_are_skipped_not_passed_through():
    """A junk entry must drop out silently without taking the valid ones with
    it, or one bad row would either crash the batch or empty the payload."""
    clean = sanitize_records([None, 7, IDENTIFYING_TICKET])
    assert len(clean) == 1
    assert set(clean[0]) == set(SAFE_TICKET_FIELDS)


# --- Redaction ----------------------------------------------------------------

@pytest.mark.parametrize("raw,marker", [
    ("write to sarah.chen@example.com now", "[redacted:email]"),
    ("call 555-867-5309 today", "[redacted:phone]"),
    ("card 4111 1111 1111 1111 charged", "[redacted:card]"),
    ("ssn 123-45-6789 on file", "[redacted:ssn]"),
])
def test_contact_details_are_replaced_with_typed_markers(raw, marker):
    out = redact_text(raw)
    assert marker in out
    for leaked in ["sarah.chen@example.com", "555-867-5309",
                   "4111 1111 1111 1111", "123-45-6789"]:
        assert leaked not in out


def test_redaction_preserves_the_surrounding_sentence():
    """A blanked body would cost the model the complaint itself. Naming the kind
    of thing removed keeps the sentence meaningful for triage."""
    out = redact_text("The email address should change to customer@julietr.com, "
                      "as there is a unique id for each product.")
    assert out.startswith("The email address should change to ")
    assert out.endswith(", as there is a unique id for each product.")


def test_non_strings_pass_through_untouched():
    """Redacting a score would be nonsense; stringifying it would corrupt the
    payload."""
    assert redact_text(87) == 87
    assert redact_text(True) is True
    assert redact_text(None) is None


def test_redaction_can_be_disabled_for_local_callers():
    [clean] = sanitize_records([IDENTIFYING_TICKET], redact=False)
    assert "sarah.chen@example.com" in clean["body"]


# --- Scored-ticket payload ----------------------------------------------------

def test_payload_carries_the_verdict_the_model_must_not_re_decide():
    safe = sanitize_scored_ticket(score_ticket(IDENTIFYING_TICKET))
    assert safe["category"] in {"Critical", "High", "Medium", "Low"}
    assert isinstance(safe["score"], int)
    assert isinstance(safe["matched_signals"], list)
    assert safe["safety_net_triggered"] is True  # "payment failed" is a hard trigger


def test_payload_category_is_unwrapped_to_a_plain_string():
    """Prompts are strings and payloads get JSON-serialised; an enum survives
    neither cleanly."""
    safe = sanitize_scored_ticket(score_ticket(IDENTIFYING_TICKET))
    assert isinstance(safe["category"], str)


def test_payload_withholds_identity():
    safe = sanitize_scored_ticket(score_ticket(IDENTIFYING_TICKET))
    assert "requester_name" not in safe
    assert "requester_email" not in safe


# --- The one that matters -----------------------------------------------------

def test_built_prompt_carries_no_identity():
    """The actual string that would be posted to the API.

    Asserts on the prompt rather than the payload because the prompt is what
    leaves the machine — a future edit that reads `scored.ticket` directly to
    add "requester: ..." would pass every test above and fail this one.
    """
    prompt = _build_user_prompt(score_ticket(IDENTIFYING_TICKET))

    for identity in ["Sarah Chen", "sarah.chen@example.com", "555-867-5309",
                     "4111 1111 1111 1111", "2024-03-02"]:
        assert identity not in prompt, f"{identity!r} leaked into the model prompt"

    # And the ticket's substance still survives, or we have sanitized the
    # payload into uselessness.
    assert "My payment failed" in prompt
    assert "payment failed" in prompt.lower()
