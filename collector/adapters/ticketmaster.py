"""Ticketmaster Discovery API v2 (needs the TICKETMASTER_API_KEY secret).

One source per city, set in sources.yaml with `params`:
    latlong: "25.79,-80.20"   radius: 12   (miles)
Queries one day at a time over the 14-day window (the API stops paging at 1,000
results per query), at about one request per second. Each event keeps its own
venue and a kind derived from Ticketmaster's classification. The source is an
aggregator, so a venue's own listing of the same show wins in dedupe.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from ..normalize import RawEvent
from .base import Context, SourceNotConfigured

API = "https://app.ticketmaster.com/discovery/v2/events.json"
PAGE_SIZE = 200
MAX_DEEP = 1000  # size * page must stay below this

SEGMENT_KIND = {
    "music": "music",
    "arts & theatre": "stage",
    "film": "film",
    "sports": "sports",
    "miscellaneous": "community",
}
GENRE_KIND = {"comedy": "stage", "theatre": "stage", "dance": "stage", "opera": "music",
              "classical": "music", "fine art": "art", "children's theatre": "stage", "lecture/seminar": "talks"}
SKIP_STATUS = {"cancelled", "canceled", "postponed", "offsale"}
TIMED_ENTRY_MIN = 4  # this many same-title slots at one venue on one day = timed-entry tickets


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(source, ctx: Context) -> list[dict[str, Any]]:
    key = ctx.secrets.get("TICKETMASTER_API_KEY")
    if not key:
        raise SourceNotConfigured("TICKETMASTER_API_KEY secret is not set")
    p = source.params
    if not p.get("latlong"):
        raise SourceNotConfigured("params.latlong is not set in sources.yaml")
    pages: list[dict[str, Any]] = []
    day = ctx.window_start
    while day < ctx.window_end:
        nxt = min(day + timedelta(days=1), ctx.window_end)
        page = 0
        while True:
            params = {
                "apikey": key,
                "latlong": p["latlong"],
                "radius": p.get("radius", 10),
                "unit": "miles",
                "startDateTime": _utc(day),
                "endDateTime": _utc(nxt),
                "size": PAGE_SIZE,
                "page": page,
                "sort": "date,asc",
                "locale": "*",
            }
            try:
                data = ctx.session.get(API, params=params, check_robots=False).json()
            except requests.RequestException as exc:  # never let the key-bearing URL reach status.json
                status = getattr(getattr(exc, "response", None), "status_code", None)
                raise RuntimeError(f"Ticketmaster API error{f' {status}' if status else ''}") from None
            pages.append(data)
            info = data.get("page") or {}
            total_pages = info.get("totalPages") or 0
            page += 1
            if page >= total_pages or (page + 1) * PAGE_SIZE > MAX_DEEP:
                break
        day = nxt
    return pages


def _kind(ev: dict[str, Any], default: str) -> str:
    for c in ev.get("classifications") or []:
        genre = ((c.get("genre") or {}).get("name") or "").lower()
        if genre in GENRE_KIND:
            return GENRE_KIND[genre]
        seg = ((c.get("segment") or {}).get("name") or "").lower()
        if seg in SEGMENT_KIND:
            return SEGMENT_KIND[seg]
    return default


def _start(dates: dict[str, Any]):
    s = dates.get("start") or {}
    if s.get("dateTime") and not s.get("timeTBA") and not s.get("noSpecificTime"):
        return datetime.fromisoformat(s["dateTime"].replace("Z", "+00:00"))
    if s.get("localDate") and s.get("localTime") and not s.get("timeTBA"):
        return datetime.fromisoformat(f"{s['localDate']}T{s['localTime']}")
    if s.get("localDate"):
        return date.fromisoformat(s["localDate"])
    return None


def collapse_timed_entry(events: list[RawEvent]) -> list[RawEvent]:
    """Attractions sell a ticket per entry slot (every 15-30 minutes); show one item per day instead."""
    groups: dict[tuple, list[RawEvent]] = {}
    for ev in events:
        day = ev.start.date() if isinstance(ev.start, datetime) else ev.start
        groups.setdefault((ev.title.casefold(), (ev.venue or "").casefold(), day), []).append(ev)
    out: list[RawEvent] = []
    for group in groups.values():
        timed = [e for e in group if isinstance(e.start, datetime)]
        if len(timed) < TIMED_ENTRY_MIN:
            out += group
            continue
        timed.sort(key=lambda e: e.start)
        first, last = timed[0], timed[-1]
        span = f"{first.start:%-I:%M %p} – {last.start:%-I:%M %p}"
        note = f"Timed entry: {len(timed)} entry times, {span}."
        # Shown in the day's all-day strip rather than as a block filling the whole day.
        first.start, first.end, first.all_day = first.start.date(), None, True
        first.source_id = f"{first.source_id}@day"
        first.description = f"{note}\n\n{first.description}" if first.description else note
        out.append(first)
    return out


def parse(payload: list[dict[str, Any]], source, ctx: Context) -> list[RawEvent]:
    out: list[RawEvent] = []
    seen: set[str] = set()
    for page in payload:
        for ev in (page.get("_embedded") or {}).get("events") or []:
            if ev.get("id") in seen or (ev.get("type") or "event") != "event":
                continue
            seen.add(ev.get("id"))
            dates = ev.get("dates") or {}
            if ((dates.get("status") or {}).get("code") or "").lower() in SKIP_STATUS:
                continue
            start = _start(dates)
            if start is None:
                continue
            end = None
            e = dates.get("end") or {}
            if e.get("dateTime"):
                end = datetime.fromisoformat(e["dateTime"].replace("Z", "+00:00"))
            venues = (ev.get("_embedded") or {}).get("venues") or []
            v = venues[0] if venues else {}
            address = ", ".join(x for x in (
                (v.get("address") or {}).get("line1"), (v.get("city") or {}).get("name")) if x)
            prices = ev.get("priceRanges") or []
            lows = [pr.get("min") for pr in prices if isinstance(pr.get("min"), (int, float))]
            highs = [pr.get("max") for pr in prices if isinstance(pr.get("max"), (int, float))]
            low = min(lows) if lows else None
            text = None
            if low is not None:
                high = max(highs) if highs else None
                text = f"${low:,.0f}" + (f" – ${high:,.0f}" if high and high > low else "")
            out.append(RawEvent(
                source_id=ev.get("id"),
                title=ev.get("name") or "",
                start=start,
                end=end,
                description=ev.get("info") or ev.get("pleaseNote") or ev.get("description"),
                url=ev.get("url"),
                location=address or None,
                venue=v.get("name") or None,
                kind=_kind(ev, source.kind),
                price_free=None if low is None else low == 0,
                price_min=float(low) if low is not None else None,
                price_text=text,
            ))
    return collapse_timed_entry(out)
