"""Merge duplicate events (SPEC.md section 5, Dedupe)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .normalize import normalize_title

MATCH_WINDOW = timedelta(minutes=15)


def _rank(event: dict[str, Any], sources: dict) -> tuple:
    src = sources.get(event["source"])
    aggregator = src.aggregator if src else False
    priority = src.priority if src else 0
    # Venue's own listing beats aggregators; then priority; then richer record.
    richness = sum(1 for k in ("end", "location", "description") if event.get(k))
    return (not aggregator, priority, richness)


def _merge_into(winner: dict[str, Any], loser: dict[str, Any]) -> None:
    listed = set(winner["also_listed_by"]) | set(loser["also_listed_by"])
    if loser["source"] != winner["source"]:
        listed.add(loser["source"])
    listed.discard(winner["source"])
    winner["also_listed_by"] = sorted(listed)
    # Fill gaps from the other listing without overriding the venue's own data.
    for key in ("end", "location", "description"):
        if not winner.get(key) and loser.get(key):
            winner[key] = loser[key]
    for key in ("free", "min", "text"):
        if winner["price"].get(key) is None and loser["price"].get(key) is not None:
            winner["price"][key] = loser["price"][key]


def dedupe(events: list[dict[str, Any]], sources: dict) -> list[dict[str, Any]]:
    # 1. Same id merges.
    by_id: dict[str, dict[str, Any]] = {}
    for ev in events:
        prev = by_id.get(ev["id"])
        if prev is None:
            by_id[ev["id"]] = ev
        else:
            _merge_into(prev, ev)

    # 2. Same normalized title, same city, start within 15 minutes.
    ranked = sorted(by_id.values(), key=lambda e: _rank(e, sources), reverse=True)
    kept: list[dict[str, Any]] = []
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for ev in ranked:
        key = (ev["city"], normalize_title(ev["title"]))
        start = datetime.fromisoformat(ev["start"])
        match = None
        for cand in index.get(key, []):
            if (
                cand["source"] != ev["source"]
                and cand["all_day"] == ev["all_day"]
                and abs(datetime.fromisoformat(cand["start"]) - start) <= MATCH_WINDOW
            ):
                match = cand
                break
        if match is not None:
            _merge_into(match, ev)
        else:
            index.setdefault(key, []).append(ev)
            kept.append(ev)
    kept.sort(key=lambda e: (datetime.fromisoformat(e["start"]), e["title"].casefold(), e["id"]))
    return kept
