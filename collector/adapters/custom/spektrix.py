"""Spektrix ticketing API v3 (Miami New Drama): every performance with its start time.

`url` is the client's API base, e.g. https://tickets.miaminewdrama.org/miaminewdrama/api/v3
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ...normalize import RawEvent


def fetch(source, ctx):
    base = source.url.rstrip("/")
    events = ctx.session.get(f"{base}/events").json()
    instances = ctx.session.get(f"{base}/instances").json()
    if not isinstance(events, list) or not isinstance(instances, list):
        raise ValueError("unexpected Spektrix response")
    return {"events": events, "instances": instances}


def parse(payload, source, ctx):
    events = {e["id"]: e for e in payload.get("events") or [] if e.get("id")}
    out = []
    for inst in payload.get("instances") or []:
        if inst.get("cancelled"):
            continue
        ev = events.get((inst.get("event") or {}).get("id"))
        if not ev or not inst.get("start"):
            continue
        start = datetime.fromisoformat(inst["start"])  # local wall time
        minutes = ev.get("duration") or 0
        end = start + timedelta(minutes=minutes) if minutes else None
        out.append(RawEvent(
            source_id=inst.get("id"),
            title=ev.get("name") or "",
            start=start,
            end=end,
            description=ev.get("description") or ev.get("htmlDescription"),
            url=ev.get("webUrl") or source.page,
            location=source.location,
        ))
    return out
