"""iCalendar feeds (Luma calendars, Refresh Miami, Miami Beach, ...).

Recurring events are expanded into one event per occurrence inside the window,
honouring RRULE/RDATE/EXDATE and RECURRENCE-ID overrides.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import icalendar
import recurring_ical_events

from ..normalize import RawEvent
from .base import Context, SourceNotConfigured


LUMA_LOOKUP = "https://api.luma.com/url?url={slug}"
LUMA_ICS = "https://api.luma.com/ics/get?entity=calendar&id={cal_id}"
_CAL_ID_RE = re.compile(r"^cal-[A-Za-z0-9]+$")


def _find_cal_id(data: Any) -> str | None:
    """Find the calendar's api_id ("cal-...") in Luma's page-lookup response."""
    if isinstance(data, dict):
        cal = data.get("calendar")
        if isinstance(cal, dict) and isinstance(cal.get("api_id"), str) and _CAL_ID_RE.match(cal["api_id"]):
            return cal["api_id"]
        for value in data.values():
            found = _find_cal_id(value)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_cal_id(value)
            if found:
                return found
    return None


def luma_feed_url(slug: str, ctx: Context) -> str:
    """Resolve a Luma calendar page name (luma.com/<slug>) to its iCal feed.

    Uses the lookup Luma's own site uses; it is not an official API, so if Luma
    changes it this source fails visibly and the feed link can be pasted as `url`.
    """
    resp = ctx.session.get(LUMA_LOOKUP.format(slug=slug))
    cal_id = _find_cal_id(resp.json())
    if not cal_id:
        raise ValueError(f"could not find a Luma calendar id for '{slug}'; paste its iCal link as url")
    return LUMA_ICS.format(cal_id=cal_id)


def fetch(source, ctx: Context) -> str:
    url = source.url
    if not url and source.luma_calendar:
        url = luma_feed_url(source.luma_calendar, ctx)
    if not url:
        raise SourceNotConfigured("no iCal feed URL set in sources.yaml")
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    resp = ctx.session.get(url)
    resp.encoding = resp.encoding or "utf-8"
    text = resp.text
    if "BEGIN:VCALENDAR" not in text[:2000]:
        raise ValueError("response is not an iCalendar feed")
    return text


# Windows time zone names some calendar systems (e.g. FIU's) put in TZID, mapped to IANA.
WINDOWS_TZ = {
    "Eastern Time (US & Canada)": "America/New_York",
    "Eastern Standard Time": "America/New_York",
    "US Eastern Standard Time": "America/Indianapolis",
    "Central Time (US & Canada)": "America/Chicago",
    "Central Standard Time": "America/Chicago",
    "Mountain Time (US & Canada)": "America/Denver",
    "Mountain Standard Time": "America/Denver",
    "Pacific Time (US & Canada)": "America/Los_Angeles",
    "Pacific Standard Time": "America/Los_Angeles",
}
_TZID_RE = re.compile(r'(TZID[=:])"?([^";:\r\n]+?)"?(?=[;:\r\n])')


def fix_windows_tzids(text: str) -> str:
    def swap(m: re.Match) -> str:
        name = m.group(2).strip()
        return m.group(1) + WINDOWS_TZ.get(name, m.group(2)) if name in WINDOWS_TZ else m.group(0)

    return _TZID_RE.sub(swap, text)


def _text(component, name: str) -> str | None:
    value = component.get(name)
    if value is None:
        return None
    return str(value)


def _dt(component, name: str) -> datetime | date | None:
    prop = component.get(name)
    return prop.dt if prop is not None else None


def parse(payload: str, source, ctx: Context) -> list[RawEvent]:
    cal = icalendar.Calendar.from_ical(fix_windows_tzids(payload))
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
