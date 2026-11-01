"""schema.org Event data embedded in pages as JSON-LD.

Handles @graph, lists, ItemList wrappers and every Event subtype
(MusicEvent, TheaterEvent, ScreeningEvent, ExhibitionEvent, ...). An event with
subEvent entries (a show run) is expanded into its performances.
"""
from __future__ import annotations

import html as htmllib
import json
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from ..normalize import RawEvent
from .base import Context, SourceNotConfigured

_SCRIPT_RE = re.compile(
    r"<script[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.I | re.S
)


def _is_event(node: dict) -> bool:
    t = node.get("@type")
    types = t if isinstance(t, list) else [t]
    return any(isinstance(x, str) and x.endswith("Event") for x in types)


def _walk(node: Any, out: list[dict]) -> None:
    if isinstance(node, list):
        for item in node:
            _walk(item, out)
    elif isinstance(node, dict):
        if _is_event(node):
            subs = node.get("subEvent") or node.get("subEvents")
            if subs:
                parent = {k: v for k, v in node.items() if k not in ("subEvent", "subEvents")}
                for sub in subs if isinstance(subs, list) else [subs]:
                    if isinstance(sub, dict):
                        out.append({**parent, **sub, "@type": sub.get("@type", parent.get("@type"))})
            else:
                out.append(node)
            return
        for value in node.values():
            if isinstance(value, (dict, list)):
                _walk(value, out)


def _loads(raw: str) -> Any:
    raw = raw.strip()
    for candidate in (raw, htmllib.unescape(raw), re.sub(r",\s*([}\]])", r"\1", raw)):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def find_events(page_html: str) -> list[dict]:
    out: list[dict] = []
    for block in _SCRIPT_RE.findall(page_html):
        data = _loads(block)
        if data is not None:
            _walk(data, out)
    return out


def fetch(source, ctx: Context) -> list[tuple[str, str]]:
    urls = [source.url] if source.url else ([source.page] if source.page else [])
    if not urls:
        raise SourceNotConfigured("no page URL set in sources.yaml")
    return [(u, ctx.session.get(u).text) for u in urls]


def _dt(value: Any) -> datetime | date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip().replace("Z", "+00:00")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return date.fromisoformat(v)
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        from dateutil import parser as dparser

        try:
            return dparser.isoparse(v)
        except (ValueError, OverflowError):
            return None


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("name") or value.get("@value")
    if isinstance(value, list) and value:
        return _text(value[0])
    return None


def _location(loc: Any) -> str | None:
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if isinstance(loc, str):
        return loc
    if not isinstance(loc, dict):
        return None
    name = loc.get("name")
    addr = loc.get("address")
    if isinstance(addr, dict):
        addr = ", ".join(
            str(addr[k]) for k in ("streetAddress", "addressLocality", "addressRegion") if addr.get(k)
        )
    parts = [p for p in (name, addr) if isinstance(p, str) and p.strip()]
    return ", ".join(dict.fromkeys(parts)) or None


def _price(offers: Any) -> tuple[bool | None, float | None, str | None]:
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if not isinstance(offers, dict):
        return None, None, None
    raw = offers.get("lowPrice", offers.get("price"))
    try:
        low = float(str(raw).replace("$", "").replace(",", "")) if raw not in (None, "") else None
    except ValueError:
        low = None
    free = None if low is None else low == 0
    text = None
    if low is not None:
        high = offers.get("highPrice")
        text = "Free" if low == 0 else (f"${low:g} – ${float(high):g}" if high not in (None, "", raw) else f"${low:g}")
    return free, low, text


def parse(payload: list[tuple[str, str]], source, ctx: Context) -> list[RawEvent]:
    out: list[RawEvent] = []
    for page_url, page_html in payload:
        for ev in find_events(page_html):
            status = str(ev.get("eventStatus") or "")
            if "Cancelled" in status or "Canceled" in status:
                continue
            start = _dt(ev.get("startDate"))
            if start is None:
                continue
            url = _text(ev.get("url")) or None
            if url:
                url = urljoin(page_url, url)
            free, low, text = _price(ev.get("offers"))
            if ev.get("isAccessibleForFree") in (True, "true", "True"):
                free, low, text = True, 0.0, "Free"
            source_id = _text(ev.get("@id")) or None
            out.append(
                RawEvent(
                    source_id=f"{source_id}@{ev.get('startDate')}" if source_id else None,
                    title=htmllib.unescape(_text(ev.get("name")) or ""),
                    start=start,
                    end=_dt(ev.get("endDate")),
                    description=_text(ev.get("description")),
                    url=url,
                    location=_location(ev.get("location")),
                    price_free=free,
                    price_min=low,
                    price_text=text,
                )
            )
    return out
