"""Oolite Arts calendar: masonry tiles, each a link with title + date/time lines."""
from __future__ import annotations

from .common import events_from_when, get_page, soup, text_of


def fetch(source, ctx) -> str:
    return get_page(source, ctx)


def parse(payload: str, source, ctx):
    out = []
    for a in soup(payload).select("a.av-masonry-entry"):
        title = text_of(a.select_one(".av-masonry-entry-title"))
        body = a.select_one(".av-masonry-entry-content")
        if not title or body is None:
            continue
        lines = [l.strip() for l in body.get_text("\n").split("\n") if l.strip()]
        when = " ".join(lines)
        # A last line that isn't a date or time is the place ("The Betsy Hotel").
        place = lines[-1] if len(lines) > 1 and not any(c.isdigit() for c in lines[-1]) else None
        out += events_from_when(when, ctx, title=title, url=a.get("href"), location=place,
                                source_id=a.get("data-av-masonry-item") or a.get("href"),
                                description=lines[0] if lines and not any(c.isdigit() for c in lines[0]) else None)
    return out
