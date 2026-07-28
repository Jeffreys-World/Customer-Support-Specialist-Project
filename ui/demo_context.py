"""Deterministic demo context for panels the dataset cannot fill.

WHY THIS EXISTS
---------------
The console is modelled on Zendesk's agent workspace, which shows a requester
identity card, a threaded conversation, and an interaction history. The Kaggle
support dataset behind this project has none of that — a record is subject, body,
tags, score, category, matched signals, rationale, and suggested queue (see
``src.schema.ScoredTicket``). Those panels would otherwise sit empty.

THE RULE
--------
Nothing derived here ever influences a decision surface. Priority, score, matched
signals, safety-net state, the rationale, and the agent's confirm/override action
are all real, and are the only things the triage claims to be real. This module
fills identity and chrome so the layout reads correctly, and every panel it feeds
is rendered with a visible "simulated" badge (``ui.components.demo_badge``).

DETERMINISM
-----------
Values are read straight out of ``sha256(ticket_id)`` rather than an RNG, so the
same ticket yields the same requester on every rerun, every machine, and every
Python version. This extends the pattern already used by
``ui.domain.simulated_age_hours`` for the SLA clock.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from typing import Dict, List

from ui.domain import simulated_age_hours
from ui.theme import Color

# Deliberately ordinary names: a reviewer should read these as placeholder demo
# data at a glance, not mistake them for a scraped customer list.
_FIRST = [
    "Rebecca", "Dwight", "Venkat", "Priya", "Marcus", "Lena", "Tomas", "Aisha",
    "Jonas", "Clara", "Omar", "Ingrid", "Diego", "Mei", "Samuel", "Nadia",
]
_LAST = [
    "Wells", "Torff", "Kumar", "Nair", "Boateng", "Fischer", "Alvarez", "Haddad",
    "Lindqvist", "Moreau", "Rahman", "Sorensen", "Castillo", "Chen", "Okafor", "Petrova",
]
_ORGS = [
    "Northwind Logistics", "Obscura Labs", "Brightline Health", "Cedarbrook Retail",
    "Halcyon Energy", "Meridian Freight", "Solstice Media", "Ravel Analytics",
]
_ZONES = [
    ("Denver", -6), ("London", 0), ("Berlin", 1), ("Bengaluru", 5),
    ("Singapore", 8), ("São Paulo", -3), ("Toronto", -5), ("Sydney", 11),
]
_AVATAR_COLORS = ["#1F73B7", "#5C6BC0", "#00838F", "#6A5ACD", "#2E8B57", "#AD5F00", "#8E44AD", "#C2185B"]

_HISTORY_TOPICS = [
    "Password reset request", "Invoice query", "Onboarding call",
    "Feature question", "Data export request", "Integration check-in",
    "Account upgrade", "Shipping delay follow-up",
]


class _Digits:
    """Pulls successive integers out of a hex digest.

    A tiny deterministic substitute for an RNG. Each ``take`` consumes four hex
    characters, so one digest supports 16 independent draws — more than enough,
    and stable forever because it depends on nothing but sha256.
    """

    def __init__(self, seed: str) -> None:
        self._hex = hashlib.sha256(seed.encode()).hexdigest()
        self._pos = 0

    def take(self, modulo: int) -> int:
        chunk = self._hex[self._pos:self._pos + 4]
        self._pos = (self._pos + 4) % (len(self._hex) - 4)
        return int(chunk, 16) % modulo


@dataclass(frozen=True)
class Requester:
    """Simulated identity for the requester panel. Never affects triage."""

    name: str
    email: str
    phone: str
    org: str
    city: str
    utc_offset: int
    customer_since: int
    avatar_color: str

    @property
    def initials(self) -> str:
        return "".join(part[0] for part in self.name.split()[:2]).upper()

    def local_time(self, now: dt.datetime | None = None) -> str:
        """Requester's wall-clock time — Zendesk shows this so agents don't call at 3am."""
        base = now or dt.datetime.now(dt.timezone.utc)
        return (base + dt.timedelta(hours=self.utc_offset)).strftime("%a %H:%M")


def requester_for(ticket: Dict) -> Requester:
    d = _Digits(ticket["id"])
    first = _FIRST[d.take(len(_FIRST))]
    last = _LAST[d.take(len(_LAST))]
    org = _ORGS[d.take(len(_ORGS))]
    city, offset = _ZONES[d.take(len(_ZONES))]
    domain = org.split()[0].lower()
    return Requester(
        name=f"{first} {last}",
        email=f"{first.lower()}.{last.lower()}@{domain}.example",
        phone=f"+1 ({200 + d.take(700)}) {100 + d.take(900):03d}-{d.take(10000):04d}",
        org=org,
        city=city,
        utc_offset=offset,
        customer_since=2016 + d.take(9),
        avatar_color=_AVATAR_COLORS[d.take(len(_AVATAR_COLORS))],
    )


@dataclass(frozen=True)
class ThreadTurn:
    author: str
    role: str  # "requester" | "agent"
    body: str
    when: str
    simulated: bool


def thread_for(ticket: Dict) -> List[ThreadTurn]:
    """The conversation thread.

    Turn one is the real ticket body. Any turns after it are simulated so the
    thread reads like a conversation rather than a single orphaned message — the
    reference layout devotes most of its width to this column.
    """
    requester = requester_for(ticket)
    age = simulated_age_hours(ticket["id"])
    d = _Digits(ticket["id"] + "thread")

    turns = [
        ThreadTurn(
            author=requester.name,
            role="requester",
            body=ticket.get("body") or "(empty ticket body)",
            when=_ago(age),
            simulated=False,  # the body is real dataset content
        )
    ]

    # Roughly two thirds of tickets get a first-response turn; the rest are still
    # awaiting one, which is what makes an unanswered queue worth triaging.
    if d.take(3) > 0:
        turns.append(
            ThreadTurn(
                author="Jordan Reyes",
                role="agent",
                body=(
                    "Thanks for flagging this — I've picked it up and I'm looking "
                    "into it now. I'll follow up as soon as I have something concrete."
                ),
                when=_ago(max(age - 0.5, 0.1)),
                simulated=True,
            )
        )
    return turns


@dataclass(frozen=True)
class HistoryItem:
    title: str
    when: str
    status: str


def history_for(ticket: Dict) -> List[HistoryItem]:
    """Prior contacts from this requester — Zendesk's interaction history panel."""
    d = _Digits(ticket["id"] + "history")
    count = 2 + d.take(3)  # 2–4 entries
    items = []
    for i in range(count):
        items.append(
            HistoryItem(
                title=_HISTORY_TOPICS[d.take(len(_HISTORY_TOPICS))],
                when=_ago((i + 1) * (24 + d.take(96))),
                status="Solved" if d.take(4) else "Open",
            )
        )
    return items


def _ago(hours: float) -> str:
    """Human-readable relative time, matching the reference's '< 1 minute ago' style."""
    if hours < 1 / 60:
        return "just now"
    if hours < 1:
        return f"{int(hours * 60)} minutes ago"
    if hours < 24:
        return f"{int(hours)} hour{'s' if int(hours) != 1 else ''} ago"
    days = int(hours // 24)
    return f"{days} day{'s' if days != 1 else ''} ago"
