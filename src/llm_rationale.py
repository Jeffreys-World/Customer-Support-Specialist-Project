"""Stage 3 — the Claude rationale layer.

Given a ticket and the rule-based scorer's verdict, this asks Claude to write a
short, plain-language "why" and to suggest which queue the ticket belongs in.

Two hard design rules (PROJECT_PLAN.md §3, §7):

  1. **Claude explains the score; it never re-decides it.** The category and
     numeric score come from ``rule_scorer`` and are passed in as fixed context.
     Claude's only outputs are ``rationale`` (bullets) and ``suggested_queue``.
  2. **No single point of failure.** If there's no API key or the call fails, the
     batch job degrades to a deterministic rule-based fallback (``fallback_*``
     below), so the queue still sorts and the UI still renders. The LLM is a
     nice-to-have explanation layer, not a dependency.

Model + structured output follow the current Anthropic SDK: the default model is
``claude-opus-4-8`` (override with ``ANTHROPIC_MODEL``), and the response is
constrained to a JSON schema via ``output_config.format`` so it always parses.

Nothing here is run in this build (no API key present) — it's written and ready
for when a key is added to ``.env``.
"""

from __future__ import annotations

import json
import os
from typing import List, Tuple

from src.schema import Category, ScoredTicket

# Default to the most capable current model; override per-run with ANTHROPIC_MODEL
# (e.g. a cheaper model such as claude-sonnet-5 / claude-haiku-4-5 when running
# rationale generation across the full ~12k-ticket batch on a tight credit).
DEFAULT_MODEL = "claude-opus-4-8"

# The dataset's real queue values — the candidate set Claude must choose from.
QUEUE_OPTIONS: List[str] = [
    "Technical Support",
    "IT Support",
    "Product Support",
    "Customer Service",
    "Billing and Payments",
    "Service Outages and Maintenance",
    "Returns and Exchanges",
    "Sales and Pre-Sales",
    "Human Resources",
    "General Inquiry",
]

SYSTEM_PROMPT = (
    "You are a triage assistant for a customer-support team. A deterministic "
    "rule-based scorer has already assigned each ticket a priority category and a "
    "0-100 urgency score. Your job is NOT to re-score or re-categorise the ticket "
    "— treat the given category and score as fixed. Explain, in plain language a "
    "busy support rep can skim, WHY that priority is reasonable, and suggest the "
    "single most appropriate queue from the provided list. Be concrete and cite "
    "what in the ticket drives the urgency. Never invent facts not in the ticket."
)

# Structured-output schema: constrains Claude to exactly the fields we consume.
# (JSON Schema array length constraints aren't supported by structured outputs,
# so the "two bullets" instruction lives in the prompt, not the schema.)
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "rationale": {
            "type": "array",
            "items": {"type": "string"},
            "description": "One or two short bullet points explaining the priority.",
        },
        "suggested_queue": {
            "type": "string",
            "enum": QUEUE_OPTIONS,
            "description": "The single best queue for this ticket.",
        },
    },
    "required": ["rationale", "suggested_queue"],
    "additionalProperties": False,
}


class RationaleUnavailable(RuntimeError):
    """Raised when the LLM layer can't run (no key / SDK / network)."""


def get_client():
    """Build an Anthropic client, loading ``.env`` if present.

    Raises :class:`RationaleUnavailable` with an actionable message when no API
    key is configured, so the batch job can cleanly fall back to score-only.
    """
    try:
        from dotenv import load_dotenv

        load_dotenv()  # populate ANTHROPIC_API_KEY from .env if it exists
    except ImportError:
        pass  # python-dotenv is optional; env vars may already be set

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RationaleUnavailable(
            "ANTHROPIC_API_KEY is not set. Add it to .env to enable live Claude "
            "rationales; the pipeline runs score-only without it."
        )

    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dependency guaranteed by requirements
        raise RationaleUnavailable("The 'anthropic' package is not installed.") from exc

    return anthropic.Anthropic()


def _build_user_prompt(scored: ScoredTicket) -> str:
    t = scored.ticket
    signals = ", ".join(scored.matched_signals) if scored.matched_signals else "none"
    net = " (Critical-class safety net was triggered by a hard-priority keyword.)" \
        if scored.safety_net_triggered else ""
    return (
        f"Ticket subject: {t.subject}\n"
        f"Ticket body: {t.body}\n\n"
        f"Rule-based verdict (fixed — do not change): "
        f"category={scored.category.value}, score={scored.score}/100.{net}\n"
        f"Keyword signals the scorer matched: {signals}.\n\n"
        f"Write one or two short bullets explaining why this priority is "
        f"appropriate, then choose the single best queue from: "
        f"{', '.join(QUEUE_OPTIONS)}."
    )


def generate_rationale(scored: ScoredTicket, client=None, model: str | None = None) -> Tuple[List[str], str]:
    """Call Claude for a rationale + suggested queue for one scored ticket.

    Returns ``(rationale_bullets, suggested_queue)``. Raises
    :class:`RationaleUnavailable` if the client can't be built; lets other
    Anthropic SDK errors propagate so the caller can decide how to handle them.
    """
    client = client or get_client()
    model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)

    response = client.messages.create(
        model=model,
        max_tokens=400,  # short, constrained completion — cheap per ticket
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA}},
        messages=[{"role": "user", "content": _build_user_prompt(scored)}],
    )

    # output_config.format guarantees the first text block is schema-valid JSON.
    text = next((b.text for b in response.content if b.type == "text"), "{}")
    data = json.loads(text)
    rationale = [str(b) for b in data.get("rationale", []) if str(b).strip()]
    suggested_queue = data.get("suggested_queue", "") or fallback_suggested_queue(scored)
    return rationale, suggested_queue


# --- Deterministic fallback (used when the LLM layer isn't run) ---------------
# Mirrors the shape of the LLM output so the UI and demo work score-only, while
# staying honestly rule-based rather than pretending to be a Claude rationale.

_QUEUE_BY_SIGNAL = [
    ({"payment failed", "billing issue"}, "Billing and Payments"),
    ({"outage", "system down", "service disruption", "unresponsive", "incident", "impact",
      "infrastructure"}, "Service Outages and Maintenance"),
    ({"security", "breach", "locked out", "can't log in", "malware", "data loss"}, "IT Support"),
    ({"error", "not working", "broken", "failure", "unexpected", "inaccessible", "blocked",
      "multiple users"}, "Technical Support"),
    ({"feature request"}, "Product Support"),
    ({"documentation", "how do I", "question"}, "General Inquiry"),
]


def fallback_suggested_queue(scored: ScoredTicket) -> str:
    """Pick a queue from matched signals alone (no LLM)."""
    signals = set(scored.matched_signals)
    for triggers, queue in _QUEUE_BY_SIGNAL:
        if signals & triggers:
            return queue
    return "Customer Service"


def fallback_rationale(scored: ScoredTicket) -> List[str]:
    """Build plain-language bullets from the scorer's own output (no LLM)."""
    bullets = [f"Rule-based score {scored.score}/100 places this in {scored.category.value}."]
    if scored.safety_net_triggered:
        bullets.append(
            "Critical-class safety net fired: a hard-priority keyword "
            f"({', '.join(scored.matched_signals[:3])}) forced at least High."
        )
    elif scored.matched_signals:
        bullets.append("Signals matched: " + ", ".join(scored.matched_signals) + ".")
    else:
        bullets.append("No priority keywords matched; defaulted to a low urgency.")
    return bullets


if __name__ == "__main__":
    # Illustrative only — this block is not run during the build (no API key).
    from src.rule_scorer import score_ticket
    from src.schema import Ticket

    demo = score_ticket(Ticket(id="demo", subject="Payment failed",
                               body="My payment failed and I'm locked out."))
    print("Fallback rationale (no key needed):")
    for b in fallback_rationale(demo):
        print("  -", b)
    print("Fallback queue:", fallback_suggested_queue(demo))
    print("\nWith ANTHROPIC_API_KEY set, generate_rationale(demo) would call Claude.")
