"""Shared adapter context. Each adapter module exposes:

    fetch(source, ctx) -> payload       # network only
    parse(payload, source, ctx) -> list[RawEvent]   # pure, tested against saved samples
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..config import City


class SourceNotConfigured(Exception):
    """The source is missing something only a human can supply (feed URL, token)."""


@dataclass
class Context:
    city: City
    now: datetime            # aware, city zone
    window_start: datetime   # aware, city zone (today 00:00)
    window_end: datetime     # aware, city zone (exclusive)
    session: object = None   # PoliteSession
    secrets: dict[str, str] = field(default_factory=dict)
