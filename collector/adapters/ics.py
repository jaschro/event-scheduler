"""iCalendar feeds (Luma calendars, Refresh Miami, Miami Beach, ...).

Recurring events are expanded into one event per occurrence inside the window,
honouring RRULE/RDATE/EXDATE and RECURRENCE-ID overrides.
"""
from __future__ import annotations

from datetime import date, datetime

import icalendar
import recurring_ical_events

from ..normalize import RawEvent
from .base import Context, SourceNotConfigured


def fetch(source, ctx: Context) -> str:
    if not source.url:
        raise SourceNotConfigured("no iCal feed URL set in sources.yaml")
    url = source.url
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    resp = ctx.session.get(url)
    resp.encoding = resp.encoding or "utf-8"
    text = resp.text
    if "BEGIN:VCALENDAR" not in text[:2000]:
        raise ValueError("response is not an iCalendar feed")
    return text


def _text(component, name: str) -> str | None:
    value = component.get(name)
    if value is None:
        return None
    return str(value)


def _dt(component, name: str) -> datetime | date | None:
    prop = component.get(name)
    return prop.dt if prop is not None else None


def parse(payload: str, source, ctx: Context) -> list[RawEvent]:
    cal = icalendar.Calendar.from_ical(payload)
    occurrences = recurring_ical_events.of(cal, skip_bad_series=True).between(
        ctx.window_start, ctx.window_end
    )
    out: list[RawEvent] = []
    for comp in occurrences:
        if comp.name != "VEVENT":
            continue
        status = (_text(comp, "STATUS") or "").upper()
        if status == "CANCELLED":
            continue
        start = _dt(comp, "DTSTART")
        if start is None:
            continue
        end = _dt(comp, "DTEND")
        if end is None and comp.get("DURATION") is not None:
            end = start + comp["DURATION"].dt
        if end == start and isinstance(start, datetime):
            end = None  # no real end given (the expander copies DTSTART); the page assumes 2 hours
        uid = _text(comp, "UID")
        is_recurring = comp.get("RRULE") is not None or comp.get("RECURRENCE-ID") is not None or comp.get("RDATE") is not None
        source_id = None
        if uid:
            source_id = f"{uid}@{start.isoformat()}" if is_recurring else uid
        out.append(
            RawEvent(
                source_id=source_id,
                title=_text(comp, "SUMMARY") or "",
                start=start,
                end=end,
                description=_text(comp, "DESCRIPTION") or _text(comp, "X-ALT-DESC"),
                url=_text(comp, "URL"),
                location=_text(comp, "LOCATION"),
            )
        )
    return out
