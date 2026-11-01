"""WordPress REST API custom post types whose fields carry the event dates.

Configured per source with `params`:
    endpoint: https://www.vanalen.org/wp-json/wp/v2/events
    start: acf.start_date_time        # dotted path into each item ("meta.x.0" for lists)
    end: acf.end_date_time            # optional
    query: {school: 33}               # optional extra query parameters
Dates are taken as local wall time in the city's zone. The newest posts are read
(events are usually posted shortly before they happen); the window does the rest.
"""
from __future__ import annotations

import html as htmllib
from datetime import date, datetime
from typing import Any

from ..normalize import RawEvent
from .base import Context, SourceNotConfigured

PAGES = 2
PER_PAGE = 100


def _path(item: Any, dotted: str | None):
    if not dotted:
        return None
    cur = item
    for part in dotted.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _when(value: Any):
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip().replace(" ", "T", 1)
    if len(v) == 10:
        return date.fromisoformat(v)
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def fetch(source, ctx: Context) -> list[list[dict[str, Any]]]:
    p = source.params
    if not p.get("endpoint") or not p.get("start"):
        raise SourceNotConfigured("params.endpoint and params.start are required")
    pages = []
    for page in range(1, PAGES + 1):
        query = {"per_page": PER_PAGE, "page": page, **(p.get("query") or {})}
        resp = ctx.session.get(p["endpoint"], params=query)
        items = resp.json()
        if not isinstance(items, list):
            raise ValueError("not a WordPress REST list")
        pages.append(items)
        total = int(resp.headers.get("X-WP-TotalPages", "1") or 1)
        if page >= total:
            break
    return pages


def parse(payload, source, ctx: Context) -> list[RawEvent]:
    p = source.params
    out = []
    for page in payload:
        for item in page:
            start = _when(_path(item, p["start"]))
            if start is None:
                continue
            title = htmllib.unescape(((item.get("title") or {}).get("rendered")) or "")
            excerpt = (item.get("excerpt") or {}).get("rendered") or (item.get("content") or {}).get("rendered")
            out.append(RawEvent(
                source_id=str(item.get("id")),
                title=title,
                start=start,
                end=_when(_path(item, p.get("end"))),
                description=excerpt,
                url=item.get("link"),
                location=source.location,
            ))
    return out
