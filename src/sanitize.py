"""Stage 3a — the model boundary.

Everything that crosses from this repo into an external model goes through here
first. The rest of the pipeline may hold whatever the dataset carries; this
module decides what a third party is allowed to see.

Three layers, because each one alone leaks:

  1. **Allowlist the fields.** ``sanitize_records`` keeps only keys named in an
     explicit allowlist and drops everything else. Denylisting ("strip
     requester_email") fails the moment the dataset grows a column nobody
     remembered to add to the list — and this dataset already grew one:
     ``requester_name`` and ``requester_email`` only became real in the dataset
     swap (see the Settings privacy panel). An allowlist fails closed instead.

  2. **Redact inside the text that survives.** ``body`` is allowlisted, because
     the whole job is explaining a ticket and the ticket is the body. But the
     body is customer prose, and customers paste things into it. Measured over
     ``data/processed/tickets.csv`` (8,469 rows): 77 bodies contain an email
     address, 30 contain a phone number, 18 contain a card-length digit run.
     An allowlist alone would pass all 125 of those straight through and read
     as if it had done its job.

  3. **Redact the identity the record already declares.** A customer signs
     their own ticket, so the name sits in the subject and body as ordinary
     prose that no pattern can catch. General NER would be the usual answer and
     is the wrong one here: probabilistic, a new dependency, and unnecessary
     when the dataset hands us ``requester_name`` in a column. Layer 1 withholds
     that column; layer 3 uses it, on the way out, to scrub the name from the
     text we keep. The field we refuse to send is what makes the field we do
     send safe.

The rule this enforces, in one line: **the model sees what the ticket is about,
never who it is about.** Triage does not need identity. `rule_scorer` never
reads these fields either — it scores ``subject`` + ``body`` — so nothing is
lost by withholding them.

Not in scope: what the *UI* displays. The requester panel deliberately shows
name and email, because the human agent triaging the ticket is the data
controller and needs them. This module is about the third party, not the agent.
"""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from src.schema import ScoredTicket

# --- Allowlists ---------------------------------------------------------------
# Ticket fields the model may see. Deliberately tiny: subject and body are the
# ticket's substance. Every other column on `Ticket` — requester_name,
# requester_email, purchase_date, csat, resolution, ... — is withheld by virtue
# of not being named here. Adding a field is a decision someone has to make on
# purpose, which is the point.
SAFE_TICKET_FIELDS: Sequence[str] = ("subject", "body")

# Scorer output the model may see. This is machine-generated verdict data, not
# customer data: `matched_signals` are keywords from the scorer's own fixed
# vocabulary, never free text lifted out of the ticket.
SAFE_VERDICT_FIELDS: Sequence[str] = (
    "category",
    "score",
    "matched_signals",
    "safety_net_triggered",
)


# --- Redaction ----------------------------------------------------------------
# Applied in this order on purpose. Email first, so an address containing digits
# is already gone before the numeric patterns run. Card before phone, so a
# 16-digit run is redacted whole rather than having its first 10 digits eaten by
# the phone pattern and the remainder left dangling.
#
# Placeholders name the *kind* of thing removed rather than blanking it, so the
# sentence still parses and the model can still reason about the complaint
# ("the email address should change to [redacted:email]" is still a request to
# change an email address).
_REDACTIONS: Sequence[tuple[re.Pattern[str], str]] = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[redacted:email]"),
    (re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"), "[redacted:ssn]"),
    # Ends on a digit, not on `\d[ -]?`, or the group swallows the space after
    # the final digit and welds the marker to the next word ("[redacted:card]was
    # charged"). Same reason the phone pattern below ends on \d{4}.
    (re.compile(r"(?<!\d)(?:\d[ -]?){12,15}\d(?!\d)"), "[redacted:card]"),
    (
        re.compile(
            r"(?<!\d)(?:\+?\d{1,2}[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)"
        ),
        "[redacted:phone]",
    ),
)


def redact_text(value: Any) -> Any:
    """Replace contact-shaped substrings in free text with typed placeholders.

    Non-strings pass through untouched so this is safe to map over a mixed
    record: redacting an ``int`` score would be nonsense, and silently
    stringifying it would corrupt the payload.
    """
    if not isinstance(value, str):
        return value
    for pattern, replacement in _REDACTIONS:
        value = pattern.sub(replacement, value)
    return value


# Shorter than this and a "name" starts matching inside ordinary words — a
# requester called "Al" would blank every "although" in the corpus. Names this
# short are also weak identifiers on their own.
_MIN_NAME_PART = 3


def identity_terms(record: Any) -> List[str]:
    """The identifying strings a record already tells us about itself.

    Names are not pattern-matchable — this is the limit of `redact_text`, and
    the reason a test caught "Sarah Chen" surviving in a subject line. General
    NER would be the usual answer and would be wrong here: it is a dependency,
    it is probabilistic, and it is unnecessary, because the dataset hands us the
    requester's name in a column. We don't need to *find* the identity, only to
    remove the one we were given.

    Returns full name and email first, then the individual name parts, so the
    caller replacing in order takes "Sarah Chen" before it takes "Sarah" and
    leaves no orphan half behind.
    """
    mapping = _as_mapping(record)
    if mapping is None:
        return []

    full_name = str(mapping.get("requester_name") or "").strip()
    email = str(mapping.get("requester_email") or "").strip()

    terms = [t for t in (full_name, email) if len(t) >= _MIN_NAME_PART]
    terms.extend(
        part for part in full_name.split()
        if len(part) >= _MIN_NAME_PART and part != full_name
    )
    # Longest first: a shorter term must never consume a substring of a longer
    # one before that longer one has had its turn.
    return sorted(dict.fromkeys(terms), key=len, reverse=True)


def redact_identity(value: Any, terms: Sequence[str]) -> Any:
    """Remove known identifying strings from free text, whole-word only.

    Word boundaries stop a surname like "Chen" from gutting "Chennai"; the
    case-insensitive match catches a body that lowercases the name it greets.
    """
    if not isinstance(value, str) or not terms:
        return value
    for term in terms:
        value = re.sub(
            rf"\b{re.escape(term)}\b", "[redacted:name]", value, flags=re.IGNORECASE
        )
    return value


def _as_mapping(record: Any) -> Mapping[str, Any] | None:
    """Read a record as a mapping, whether it's a dict or a dataclass.

    The pipeline holds `Ticket` dataclasses in memory but dicts once a batch has
    been written to `classified_tickets.json`. Callers should not have to care
    which side of that boundary they are on.
    """
    if isinstance(record, Mapping):
        return record
    if is_dataclass(record) and not isinstance(record, type):
        return asdict(record)
    return None


def sanitize_records(
    records: Iterable[Any],
    safe_fields: Sequence[str] = SAFE_TICKET_FIELDS,
    *,
    redact: bool = True,
) -> List[Dict[str, Any]]:
    """Keep ONLY the allowlisted fields of each record, and redact what's left.

    Returns a list of plain dicts — never the original objects — so a caller
    cannot reach a withheld field through a reference it was handed back.

    A record that isn't dict-like, and any non-iterable input, yields nothing
    rather than raising: this sits on the path to an external API, and the safe
    failure there is an empty payload, not a traceback that a caller might catch
    and paper over with the unsanitized original.
    """
    if isinstance(records, (str, bytes, Mapping)) or not isinstance(records, Iterable):
        return []

    clean_records: List[Dict[str, Any]] = []
    for record in records:
        mapping = _as_mapping(record)
        if mapping is None:
            continue
        # Derived from the FULL record, then applied to the allowlisted subset.
        # The withheld `requester_name` is exactly what lets us scrub the name
        # out of the `body` we keep — dropping the column is not enough on its
        # own, because the customer signs their own ticket.
        terms = identity_terms(mapping) if redact else []
        clean: Dict[str, Any] = {}
        for field_name in safe_fields:
            if field_name in mapping:
                value = mapping[field_name]
                if redact:
                    value = redact_identity(redact_text(value), terms)
                clean[field_name] = value
        clean_records.append(clean)
    return clean_records


def sanitize_scored_ticket(
    scored: ScoredTicket, *, redact: bool = True
) -> Dict[str, Any]:
    """Build the one payload allowed to describe a scored ticket to a model.

    Flattens the ticket's allowlisted fields and the scorer's verdict into a
    single dict. ``category`` is unwrapped from its enum to its ``.value`` so
    the payload is JSON-serialisable and readable in a prompt.

    This is the only function `llm_rationale` should use to read a ticket. It
    takes the whole `ScoredTicket` and hands back a dict precisely so the prompt
    builder never holds a reference to `scored.ticket` and cannot reach
    `requester_name` even by accident.
    """
    payload = sanitize_records([scored.ticket], SAFE_TICKET_FIELDS, redact=redact)
    clean: Dict[str, Any] = payload[0] if payload else {}

    for field_name in SAFE_VERDICT_FIELDS:
        value = getattr(scored, field_name, None)
        if value is None:
            continue
        # Category is an enum; everything else is already a primitive or a list
        # of scorer-owned keyword strings.
        clean[field_name] = getattr(value, "value", value)
    return clean
