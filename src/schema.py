"""Shared data structures for Jordan's Ticket Triage Assistant.

Every stage of the pipeline speaks in these types:

    data_prep      -> writes rows the loaders turn into ``Ticket``
    rule_scorer    -> turns a ``Ticket`` into a ``ScoredTicket``
    llm_rationale  -> fills in ``rationale`` / ``suggested_queue`` on a ``ScoredTicket``
    batch_classify -> serialises ``ScoredTicket`` records to JSON for the UI
    app (Streamlit)-> reads those records back and renders the queue

Keeping the shapes here (rather than passing bare dicts around) means the
Critical-class safety net, the evaluator, and the UI all agree on what a
"category" is and how a numeric score maps onto one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Category(str, Enum):
    """Product-facing priority scale (four levels).

    Inherits from ``str`` so members serialise straight to JSON as their value.

    The current dataset (``customer_support_tickets.csv``) labels tickets on this
    exact four-level scale, Critical included, so the product scale and the ground
    truth are the same vocabulary and no collapsing is needed. The earlier
    multilingual dataset topped out at ``high``, which is why
    :meth:`ground_truth_bucket` exists at all — see its docstring.
    """

    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"

    @property
    def emoji(self) -> str:
        return {
            Category.CRITICAL: "🔴",
            Category.HIGH: "🟠",
            Category.MEDIUM: "🟡",
            Category.LOW: "🟢",
        }[self]

    @property
    def rank(self) -> int:
        """Higher = more urgent. Used for sorting and ``>=`` comparisons."""
        return {
            Category.LOW: 0,
            Category.MEDIUM: 1,
            Category.HIGH: 2,
            Category.CRITICAL: 3,
        }[self]

    def at_least(self, other: "Category") -> bool:
        """True if this category is ``other`` or more urgent."""
        return self.rank >= other.rank

    def ground_truth_bucket(self) -> str:
        """The label this category is compared against during evaluation.

        Now an identity mapping. The current dataset labels tickets on the same
        four-level scale the product uses, so a prediction is compared to the
        ground truth directly and "Critical" means Critical.

        This used to collapse Critical and High into a single ``high`` bucket,
        because the previous dataset had no Critical label and scoring against it
        otherwise would have marked every correct Critical call as wrong. Kept as
        a named seam so a future dataset with a coarser scale has one obvious
        place to reintroduce a mapping.
        """
        return self.value

    def top_severity(self) -> bool:
        """True for the Critical-class bucket (Critical or High).

        Recall over this bucket is the metric tied to Jordan's 4-hour billing
        incident: a top-severity ticket read as routine is the costliest failure.
        """
        return self is Category.CRITICAL or self is Category.HIGH

    @classmethod
    def from_score(cls, score: int) -> "Category":
        """Bucket a 0–100 urgency score into a category (PROJECT_PLAN.md §5)."""
        if score >= 90:
            return cls.CRITICAL
        if score >= 65:
            return cls.HIGH
        if score >= 35:
            return cls.MEDIUM
        return cls.LOW


# Canonical dataset priority labels, ordered least → most urgent. Identical to
# the product scale now that the dataset carries a real Critical label.
DATASET_LABELS: List[str] = [
    Category.LOW.value,
    Category.MEDIUM.value,
    Category.HIGH.value,
    Category.CRITICAL.value,
]


@dataclass
class Ticket:
    """One incoming support ticket, as loaded from the processed dataset."""

    id: str
    subject: str
    body: str
    # Ground-truth fields from the dataset (used for evaluation, not scoring).
    true_priority: str = ""          # one of DATASET_LABELS
    true_queue: str = ""
    tags: List[str] = field(default_factory=list)

    # Operational fields carried straight through from the dataset. The dashboard
    # reads these; the scorer never does. `csat`, `first_response_at`,
    # `resolved_at` and `resolution` are only populated for closed tickets, so
    # anything consuming them must handle the empty string.
    status: str = ""
    channel: str = ""
    product: str = ""
    ticket_type: str = ""
    csat: str = ""
    first_response_at: str = ""
    resolved_at: str = ""
    # The agent's free-text closing note. Empty for anything not yet closed —
    # `ui.domain.resolution_state` owns the label shown in that case, so no
    # sentinel string is stored here.
    resolution: str = ""
    purchase_date: str = ""
    requester_name: str = ""
    requester_email: str = ""

    @property
    def text(self) -> str:
        """Subject + body, the text the scorer and LLM read."""
        return f"{self.subject}\n\n{self.body}".strip()


@dataclass
class ScoredTicket:
    """A ticket after the rule-based scorer (and, optionally, the LLM layer)."""

    ticket: Ticket
    score: int
    category: Category
    matched_signals: List[str] = field(default_factory=list)
    safety_net_triggered: bool = False

    # Filled in by the LLM rationale layer when a key is available; left empty
    # in score-only runs so the pipeline never blocks on the API.
    rationale: List[str] = field(default_factory=list)
    suggested_queue: str = ""

    # Filled in by the UI when an agent confirms or overrides the category.
    override_category: Optional[str] = None

    def to_dict(self) -> Dict:
        """Flatten to a JSON-serialisable dict for ``classified_tickets.json``."""
        return {
            "id": self.ticket.id,
            "subject": self.ticket.subject,
            "body": self.ticket.body,
            "true_priority": self.ticket.true_priority,
            "true_queue": self.ticket.true_queue,
            "tags": self.ticket.tags,
            "status": self.ticket.status,
            "channel": self.ticket.channel,
            "product": self.ticket.product,
            "ticket_type": self.ticket.ticket_type,
            "csat": self.ticket.csat,
            "first_response_at": self.ticket.first_response_at,
            "resolved_at": self.ticket.resolved_at,
            "resolution": self.ticket.resolution,
            "purchase_date": self.ticket.purchase_date,
            "requester_name": self.ticket.requester_name,
            "requester_email": self.ticket.requester_email,
            "score": self.score,
            "category": self.category.value,
            "matched_signals": self.matched_signals,
            "safety_net_triggered": self.safety_net_triggered,
            "rationale": self.rationale,
            "suggested_queue": self.suggested_queue,
            "override_category": self.override_category,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ScoredTicket":
        ticket = Ticket(
            id=str(d.get("id", "")),
            subject=d.get("subject", ""),
            body=d.get("body", ""),
            true_priority=d.get("true_priority", ""),
            true_queue=d.get("true_queue", ""),
            tags=list(d.get("tags", []) or []),
            status=d.get("status", ""),
            channel=d.get("channel", ""),
            product=d.get("product", ""),
            ticket_type=d.get("ticket_type", ""),
            csat=d.get("csat", ""),
            first_response_at=d.get("first_response_at", ""),
            resolved_at=d.get("resolved_at", ""),
            resolution=d.get("resolution", ""),
            purchase_date=d.get("purchase_date", ""),
            requester_name=d.get("requester_name", ""),
            requester_email=d.get("requester_email", ""),
        )
        return cls(
            ticket=ticket,
            score=int(d.get("score", 0)),
            category=Category(d.get("category", Category.LOW.value)),
            matched_signals=list(d.get("matched_signals", []) or []),
            safety_net_triggered=bool(d.get("safety_net_triggered", False)),
            rationale=list(d.get("rationale", []) or []),
            suggested_queue=d.get("suggested_queue", ""),
            override_category=d.get("override_category"),
        )
