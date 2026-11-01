"""WordPress sites running The Events Calendar: /wp-json/tribe/events/v1/events."""
from __future__ import annotations

import html as htmllib
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from ..normalize import RawEvent
from .base import Context, SourceNotConfigured

MAX_PAGES = 10


def source_query(source) -> dict[str, str]:
    from urllib.parse import parse_qsl

    url = source.url or ""
    return dict(parse_qsl(url.split("?", 1)[1])) if "/wp-json/tribe/events/v1/events?" in url else {}


def api_base(source) -> str:
    url = source.url or source.page
    if not url:
        raise SourceNotConfigured("no page URL set in sources.yaml")
    if "/wp-json/tribe/events/v1/events" in url:
        return url.split("?")[0]
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}/wp-json/tribe/events/v1/events"


def fetch(source, ctx: Context) -> list[dict[str, Any]]:
    url = api_base(source)
    params: dict[str, Any] | None = {
        "start_date": ctx.window_start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": ctx.window_end.strftime("%Y-%m-%d %H:%M:%S"),
        "per_page": 50,
        **source_query(source),
    }
    pages = []
    for _ in range(MAX_PAGES):
        data = ctx.session.get(url, params=params).json()
        if not isinstance(data, dict) or "events" not in data:
            raise ValueError("response is not The Events Calendar API")
        pages.append(data)
        nxt = data.get("next_rest_url")
        if not nxt:
            break
        url, params = nxt, None
    return pages


def _utc(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _local_date(value: str | None):
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").date() if value else None


def parse(payload: list[dict[str, Any]], source, ctx: Context) -> list[RawEvent]:
    out = []
    for page in payload:
        for ev in page.get("events") or []:
            if ev.get("status") not in (None, "publish"):
                continue
            all_day = bool(ev.get("all_day"))
            if all_day:
                start, end = _local_date(ev.get("start_date")), _local_date(ev.get("end_date"))
                if end is not None:
                    from datetime import timedelta

                    end = end + timedelta(days=1)  # API gives the last day; schema wants exclusive end
            else:
                start, end = _utc(ev.get("utc_start_date")), _utc(ev.get("utc_end_date"))
            venue = ev.get("venue") if isinstance(ev.get("venue"), dict) else {}
            location = ", ".join(
                p for p in (venue.get("venue"), venue.get("address"), venue.get("city")) if p
            ) or None
            cost = htmllib.unescape(ev.get("cost") or "") or None
            values = (ev.get("cost_details") or {}).get("values") or []
            try:
                low = min(float(v) for v in values) if values else None
            except ValueError:
                low = None
            free = True if cost and cost.strip().lower() == "free" else (None if low is None else low == 0)
            out.append(
                RawEvent(
                    source_id=str(ev.get("id")) if ev.get("id") else None,
                    title=htmllib.unescape(ev.get("title") or ""),
                    start=start,
                    end=end,
                    all_day=all_day,
                    description=ev.get("description") or ev.get("excerpt"),
                    url=ev.get("url"),
                    location=location,
                    price_free=free,
                    price_min=0.0 if free and low is None else low,
                    price_text=cost,
                )
            )
    return out
