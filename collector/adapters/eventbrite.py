"""Eventbrite organizers via the official API v3 (needs EVENTBRITE_TOKEN)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from ..normalize import RawEvent
from .base import Context, SourceNotConfigured

API = "https://www.eventbriteapi.com/v3"
MAX_PAGES = 10


def fetch(source, ctx: Context) -> list[dict[str, Any]]:
    token = ctx.secrets.get("EVENTBRITE_TOKEN")
    if not token:
        raise SourceNotConfigured("EVENTBRITE_TOKEN secret is not set")
    if not source.organizer_id:
        raise SourceNotConfigured("no organizer_id set in sources.yaml")
    pages: list[dict[str, Any]] = []
    # Only parameters the "events by organizer" endpoint documents; it answers 400 to others
    # (such as time_filter). "live" means published and not yet ended.
    params = {
        "status": "live",
        "order_by": "start_asc",
        "only_public": "true",
        "expand": "venue,ticket_availability",
    }
    for _ in range(MAX_PAGES):
        try:
            resp = ctx.session.get(
                f"{API}/organizers/{source.organizer_id}/events/",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                check_robots=False,  # official, authenticated API
            )
        except requests.HTTPError as exc:
            raise RuntimeError(f"Eventbrite API {_describe(exc.response)}") from None
        data = resp.json()
        pages.append(data)
        pag = data.get("pagination") or {}
        if not pag.get("has_more_items") or not pag.get("continuation"):
            break
        params["continuation"] = pag["continuation"]
    return pages


def _describe(resp) -> str:
    """Status plus Eventbrite's own error text, without echoing the request URL."""
    if resp is None:
        return "error"
    detail = ""
    try:
        body = resp.json()
        detail = body.get("error_description") or body.get("error") or ""
    except ValueError:
        detail = (resp.text or "")[:200]
    return f"{resp.status_code}: {detail}".rstrip(": ")


def _when(block: dict[str, Any] | None) -> datetime | None:
    if not block or not block.get("utc"):
        return None
    return datetime.fromisoformat(block["utc"].replace("Z", "+00:00"))


def parse(payload: list[dict[str, Any]], source, ctx: Context) -> list[RawEvent]:
    out: list[RawEvent] = []
    for page in payload:
        for ev in page.get("events") or []:
            if ev.get("status") not in (None, "live", "started"):
                continue
            start = _when(ev.get("start"))
            if start is None:
                continue
            venue = ev.get("venue") or {}
            address = (venue.get("address") or {}).get("localized_address_display")
            location = ", ".join(p for p in (venue.get("name"), address) if p) or None
            if ev.get("online_event"):
                location = location or "Online"

            ta = ev.get("ticket_availability") or {}
            min_price = ta.get("minimum_ticket_price") or {}
            max_price = ta.get("maximum_ticket_price") or {}
            is_free = ev.get("is_free")
            price_min = None
            price_text = None
            if is_free:
                price_min, price_text = 0.0, "Free"
            elif min_price.get("major_value") is not None:
                price_min = float(min_price["major_value"])
                lo, hi = min_price.get("display"), max_price.get("display")
                price_text = f"{lo} – {hi}" if hi and hi != lo else lo
            if ta.get("is_sold_out"):
                price_text = f"{price_text} (sold out)" if price_text else "Sold out"

            out.append(
                RawEvent(
                    source_id=str(ev.get("id")) if ev.get("id") else None,
                    title=(ev.get("name") or {}).get("text") or "",
                    start=start,
                    end=_when(ev.get("end")),
                    description=(ev.get("description") or {}).get("text") or ev.get("summary"),
                    url=ev.get("url"),
                    location=location,
                    price_free=bool(is_free) if is_free is not None else None,
                    price_min=price_min,
                    price_text=price_text,
                )
            )
    return out
