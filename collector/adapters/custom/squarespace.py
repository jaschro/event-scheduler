"""Squarespace event collections (Miami Beach Botanical Garden): <page>?format=json.

Squarespace serves every events page as JSON when asked; "upcoming" holds the
events with start/end as epoch milliseconds.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urljoin

from ...normalize import RawEvent


def fetch(source, ctx):
    url = (source.url or source.page).split("?")[0]
    data = ctx.session.get(url, params={"format": "json"}).json()
    if "upcoming" not in data:
        raise ValueError("not a Squarespace events collection")
    return data


def _ms(v):
    return datetime.fromtimestamp(v / 1000, tz=timezone.utc) if isinstance(v, (int, float)) else None


def parse(payload, source, ctx):
    out = []
    for item in payload.get("upcoming") or []:
        start = _ms(item.get("startDate"))
        if start is None:
            continue
        loc = item.get("location") or {}
        where = ", ".join(p for p in (loc.get("addressTitle"), loc.get("addressLine1")) if p) or None
        out.append(RawEvent(
            source_id=item.get("id"),
            title=(item.get("title") or "").strip(),
            start=start,
            end=_ms(item.get("endDate")),
            description=item.get("excerpt") or item.get("body"),
            url=urljoin(source.page, item.get("fullUrl") or ""),
            location=where,
        ))
    return out
