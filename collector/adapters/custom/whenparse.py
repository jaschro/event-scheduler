"""Turn the date/time text venue pages print into concrete occurrences.

Handles what the Miami venue pages actually use, for example:
    "Saturday, Nov. 7, 2026" + "10:30 a.m. - 12:30 p.m."
    "Thu, Feb 18 | 7:30 PM - 9:30 PM"           (no year: nearest sensible year)
    "Thursdays 6 - 8:30 p.m." + "Oct. 29 - Nov. 19, 2026"   (weekly series)
    "Tuesdays 10 a.m. - 1 p.m." + "Dec. 8 & 15, 2026"       (date list)
    "NOV 5–29, 2026"                             (run of days, no times)
Returns naive local datetimes (or dates when no time is given); the caller's
city zone is applied later by normalize.build_event.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?"
_DASH = r"\s*(?:-|–|—|to|through|thru)\s*"
# "Nov. 7, 2026" / "November 7" / "Nov 7th 2026"
_DATE = rf"{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?"
_TIME = r"(\d{1,2})(?::(\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?|noon)?"

DATE_RANGE_RE = re.compile(rf"\b{_DATE}{_DASH}(?:{_MON}\s+)?(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?", re.I)
DATE_LIST_RE = re.compile(rf"\b{_MON}\s+(\d{{1,2}})(?!\d)((?:\s*(?:,|&|and)\s*\d{{1,2}}(?!\d)(?!:))+)(?:,?\s+(\d{{4}}))?", re.I)
DATE_RE = re.compile(rf"\b{_DATE}", re.I)
NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
TIME_RANGE_RE = re.compile(rf"\b{_TIME}{_DASH}{_TIME}", re.I)
TIME_RE = re.compile(rf"\b{_TIME}", re.I)
_TIME_M = r"(\d{1,2})(?::(\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?)"
TIME_PAIR_RE = re.compile(rf"\b{_TIME_M}\s+{_TIME_M}", re.I)  # "9:30 PM 10:30 PM"
WEEKLY_RE = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*days\b", re.I)


@dataclass
class When:
    start: datetime | date
    end: datetime | date | None = None


def _year_for(month: int, day: int, today: date) -> int:
    """No year printed: pick the year that puts the date closest to today (within ~6 months back)."""
    best = today.year
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if (today - timedelta(days=183)) <= d < (today + timedelta(days=183)):
            best = y
    return best


def _mk_date(mon: str, day: str, year: str | None, today: date) -> date | None:
    m = MONTHS.get(mon.lower()[:4].rstrip(".")) or MONTHS.get(mon.lower()[:3])
    if not m:
        return None
    d = int(day)
    y = int(year) if year else _year_for(m, d, today)
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _hour(h: str, mnt: str | None, mer: str | None) -> time | None:
    hh = int(h)
    mm = int(mnt) if mnt else 0
    if mer:
        m = mer.lower().replace(".", "").replace(" ", "")
        if m == "noon":
            return time(12, mm)
        if m.startswith("p") and hh < 12:
            hh += 12
        if m.startswith("a") and hh == 12:
            hh = 0
    if not (0 <= hh < 24 and 0 <= mm < 60):
        return None
    return time(hh, mm)


def parse_times(text: str) -> tuple[time | None, time | None]:
    """First time range (or single time) in the text. "6 - 8:30 p.m." → 18:00–20:30."""
    m = TIME_RANGE_RE.search(text)
    if m:
        h1, m1, mer1, h2, m2, mer2 = m.groups()
        if mer1 or mer2:
            t2 = _hour(h2, m2, mer2)
            mer1 = mer1 or mer2
            t1 = _hour(h1, m1, mer1)
            # "11 - 1 p.m.": the start was in the morning.
            if t1 and t2 and t1 > t2 and not m.group(3):
                t1 = _hour(h1, m1, "am")
            return t1, t2
    m = TIME_PAIR_RE.search(text)
    if m:
        return _hour(*m.groups()[:3]), _hour(*m.groups()[3:])
    for m in TIME_RE.finditer(text):
        h, mnt, mer = m.groups()
        if mer or mnt:  # a bare number is a date or count, not a time
            if not mer and not (0 < int(h) <= 23):
                continue
            t = _hour(h, mnt, mer or ("pm" if 1 <= int(h) <= 9 else None))
            if t:
                return t, None
    return None, None


def _combine(d: date, t1: time | None, t2: time | None) -> When:
    if t1 is None:
        return When(d, None)
    start = datetime.combine(d, t1)
    end = None
    if t2 is not None:
        end = datetime.combine(d, t2)
        if end <= start:
            end += timedelta(days=1)
    return When(start, end)


def parse_when(text: str, today: date) -> list[When]:
    """All occurrences described by one event's date/time text."""
    text = " ".join(text.replace(" ", " ").split())
    t1, t2 = parse_times(text)

    # Series: "Tuesdays ... Dec. 8 & 15, 2026"
    m = DATE_LIST_RE.search(text)
    if m:
        mon, first, rest, year = m.group(1), m.group(2), m.group(3), m.group(4)
        days = [first] + re.findall(r"\d{1,2}", rest)
        dates = [d for d in (_mk_date(mon, x, year, today) for x in days) if d]
        if dates:
            return [_combine(d, t1, t2) for d in dates]

    # Range: weekly series when a weekday plural is given, else one multi-day span.
    m = DATE_RANGE_RE.search(text)
    if m:
        mon1, d1, y1, mon2, d2, y2 = m.groups()
        year = y1 or y2
        start = _mk_date(mon1, d1, y1 or y2, today)
        end = _mk_date(mon2 or mon1, d2, y2 or year, today)
        if start and end:
            if end < start and not y1:  # "Dec 28 - Jan 3, 2027"
                start = start.replace(year=start.year - 1)
            weekly = WEEKLY_RE.search(text)
            if weekly:
                wd = WEEKDAYS[weekly.group(1).lower()[:3]]
                out, d = [], start
                while d <= end:
                    if d.weekday() == wd:
                        out.append(_combine(d, t1, t2))
                    d += timedelta(days=1)
                if out:
                    return out
            if t1 is not None and start == end:
                return [_combine(start, t1, t2)]
            return [When(start, end + timedelta(days=1))]  # all-day span, exclusive end

    m = DATE_RE.search(text)
    if m:
        d = _mk_date(m.group(1), m.group(2), m.group(3), today)
        if d:
            return [_combine(d, t1, t2)]

    m = NUMERIC_DATE_RE.search(text)
    if m:
        mo, dy, yr = int(m.group(1)), int(m.group(2)), m.group(3)
        if 1 <= mo <= 12 and 1 <= dy <= 31:
            y = (int(yr) + 2000 if len(yr) == 2 else int(yr)) if yr else _year_for(mo, dy, today)
            try:
                return [_combine(date(y, mo, dy), t1, t2)]
            except ValueError:
                pass
    return []
