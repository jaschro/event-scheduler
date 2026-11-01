"""Turn adapter output into the event schema of SPEC.md section 4."""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

DESCRIPTION_LIMIT = 600

_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_TAG_RE = re.compile(r"(?i)<\s*(br|/p|/div|/li|/h[1-6])\b[^>]*>")
_SCRIPT_RE = re.compile(r"(?is)<(script|style)\b.*?</\1\s*>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_NL_RE = re.compile(r"\n\s*\n+")
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_TITLE_NORM_RE = re.compile(r"[^\w\s]", re.UNICODE)


@dataclass
class RawEvent:
    """What an adapter produces. Times may be naive (= city local), aware, or dates (all-day)."""

    source_id: str | None
    title: str
    start: datetime | date
    end: datetime | date | None = None
    description: str | None = None
    url: str | None = None
    location: str | None = None
    price_free: bool | None = None
    price_min: float | None = None
    price_text: str | None = None
    all_day: bool | None = None  # inferred from start type when None
    venue: str | None = None     # aggregators: the event's real venue (default: source name)
    kind: str | None = None      # aggregators: per-event kind (default: source kind)


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = _SCRIPT_RE.sub(" ", text)
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text).replace(" ", " ")
    lines = [_WS_RE.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    return _NL_RE.sub("\n\n", text).strip()


def plain_one_line(text: str | None) -> str:
    return " ".join(strip_html(text).split())


def trim(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:.-\n") + "…"


def safe_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if re.match(r"(?i)^https?://[^\s]+$", url):
        return url
    return None


def first_url(text: str | None) -> str | None:
    if not text:
        return None
    m = _URL_RE.search(text)
    return safe_url(m.group(0).rstrip(".,;")) if m else None


def normalize_title(title: str) -> str:
    t = _TITLE_NORM_RE.sub(" ", title.casefold())
    return " ".join(t.split())


def make_id(source: str, source_id: str | None, title: str, start_iso: str) -> str:
    basis = f"{source}|{source_id}" if source_id else f"{source}|{normalize_title(title)}|{start_iso}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def to_local(value: datetime | date, tz: ZoneInfo) -> datetime:
    """Datetime in the city zone. Naive datetimes are taken as city-local; dates become midnight."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=tz)
        return value.astimezone(tz)
    return datetime.combine(value, time(0, 0), tzinfo=tz)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def build_event(raw: RawEvent, *, source, city, fetched_at: str) -> dict[str, Any] | None:
    """Build a schema event dict, or None if it lacks a title/start."""
    title = plain_one_line(raw.title)
    if not title or raw.start is None:
        return None
    tz = city.tz
    all_day = raw.all_day if raw.all_day is not None else not isinstance(raw.start, datetime)
    start = to_local(raw.start, tz)
    end = to_local(raw.end, tz) if raw.end is not None else None
    if all_day:
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        if end is None or end <= start:
            end = start + timedelta(days=1)
    if end is not None and end < start:
        end = None
    if end is None and not all_day and getattr(source, "default_minutes", None):
        end = start + timedelta(minutes=source.default_minutes)

    description_full = strip_html(raw.description)
    url = safe_url(raw.url) or first_url(description_full) or safe_url(source.page)
    location = plain_one_line(raw.location) or source.location or None

    price_text = plain_one_line(raw.price_text) or None
    free = raw.price_free
    if free is None and raw.price_min is not None:
        free = raw.price_min == 0
    start_iso = iso(start)
    return {
        "id": make_id(source.key, raw.source_id, title, start_iso),
        "title": title,
        "venue": plain_one_line(raw.venue) or source.name,
        "kind": raw.kind or source.kind,
        "start": start_iso,
        "end": iso(end) if end else None,
        "all_day": all_day,
        "description": trim(description_full),
        "url": url,
        "location": location,
        "price": {"free": free, "min": raw.price_min, "text": price_text},
        "source": source.key,
        "also_listed_by": [],
        "fetched_at": fetched_at,
        "city": city.key,
    }


def effective_end(event: dict[str, Any], default_hours: float) -> datetime:
    start = datetime.fromisoformat(event["start"])
    if event.get("end"):
        return datetime.fromisoformat(event["end"])
    if event.get("all_day"):
        return start + timedelta(days=1)
    return start + timedelta(hours=default_hours)


def in_window(event: dict[str, Any], now: datetime, window_end: datetime, default_hours: float) -> bool:
    """Keep events that have not ended and start before the window closes."""
    start = datetime.fromisoformat(event["start"])
    return effective_end(event, default_hours) > now and start < window_end


def passes_filter(event: dict[str, Any], rules: dict[str, list[str]]) -> bool:
    if not rules:
        return True
    hay = event["title"] if rules.get("fields") == "title" else f"{event['title']}\n{event['description']}"
    include = rules.get("include") or []
    exclude = rules.get("exclude") or []
    if include and not any(re.search(p, hay) for p in include):
        return False
    return not any(re.search(p, hay) for p in exclude)
