"""Load and validate sources.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

KINDS = {
    "tech", "museum", "art", "film", "stage", "music", "talks", "science",
    "food and wine", "wellness", "community", "outdoors",
}
METHODS = {"ics", "eventbrite", "tribe", "jsonld", "custom", "browser"}

DEFAULT_SETTINGS = {
    "days_ahead": 14,
    "user_agent": "EventSchedulerBot/0.1",
    "request_delay_seconds": 1.0,
    "request_timeout_seconds": 30,
    "source_timeout_seconds": 120,
    "default_duration_hours": 2,
}


@dataclass(frozen=True)
class City:
    key: str
    name: str
    tz: ZoneInfo


@dataclass
class Source:
    key: str
    name: str
    city: str
    kind: str
    method: str
    enabled: bool = True
    url: str | None = None
    organizer_id: str | None = None
    page: str | None = None
    location: str | None = None
    aggregator: bool = False
    priority: int = 50
    filter: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Config:
    settings: dict[str, Any]
    cities: dict[str, City]
    sources: list[Source]


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    settings = {**DEFAULT_SETTINGS, **(raw.get("settings") or {})}

    cities: dict[str, City] = {}
    for c in raw.get("cities") or []:
        if c["key"] in cities:
            raise ValueError(f"duplicate city key {c['key']!r}")
        cities[c["key"]] = City(key=c["key"], name=c["name"], tz=ZoneInfo(c["tz"]))
    if not cities:
        raise ValueError("sources.yaml needs at least one city")

    sources: list[Source] = []
    seen: set[str] = set()
    for s in raw.get("sources") or []:
        src = Source(
            key=s["key"],
            name=s["name"],
            city=s["city"],
            kind=s["kind"],
            method=s["method"],
            enabled=s.get("enabled", True),
            url=s.get("url"),
            organizer_id=str(s["organizer_id"]) if s.get("organizer_id") else None,
            page=s.get("page"),
            location=s.get("location"),
            aggregator=bool(s.get("aggregator", False)),
            priority=int(s.get("priority", 10 if s.get("aggregator") else 50)),
            filter=s.get("filter") or {},
        )
        if src.key in seen:
            raise ValueError(f"duplicate source key {src.key!r}")
        seen.add(src.key)
        if src.city not in cities:
            raise ValueError(f"source {src.key!r}: unknown city {src.city!r}")
        if src.kind not in KINDS:
            raise ValueError(f"source {src.key!r}: unknown kind {src.kind!r}")
        if src.method not in METHODS:
            raise ValueError(f"source {src.key!r}: unknown method {src.method!r}")
        sources.append(src)
    return Config(settings=settings, cities=cities, sources=sources)
