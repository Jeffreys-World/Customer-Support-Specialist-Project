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
    The dataset only labels tickets ``low/medium/high`` — there is no Critical
    label — so :meth:`ground_truth_bucket` collapses this four-level scale back
    onto the dataset's three levels for honest evaluation. See PROJECT_PLAN.md
    §5 and the plan's "Critical label" decision.
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
        """Map the four-level product scale onto the dataset's three labels.

        Critical and High both map to the dataset's top-severity ``high`` bucket,
        so "Critical-class recall" is measured as: of tickets truly labelled
        ``high``, how many did the scorer flag Critical *or* High.
        """
        if self is Category.CRITICAL or self is Category.HIGH:
            return "high"
        if self is Category.MEDIUM:
            return "medium"
        return "low"

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


# Canonical dataset priority labels, ordered least → most urgent.
DATASET_LABELS: List[str] = ["low", "medium", "high"]


@dataclass
class Ticket:
    """One incoming support ticket, as loaded from the processed dataset."""

    id: str
    subject: str
    body: str
    # Ground-truth fields from the dataset (used for evaluation, not scoring).
    true_priority: str = ""          # one of DATASET_LABELS
    true_queue: str = ""
    language: str = ""
    tags: List[str] = field(default_factory=list)

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
            "language": self.ticket.language,
            "tags": self.ticket.tags,
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
            language=d.get("language", ""),
            tags=list(d.get("tags", []) or []),
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
