"""Helpers shared by the page readers."""
from __future__ import annotations

from bs4 import BeautifulSoup

from ...normalize import RawEvent
from .whenparse import parse_when


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def text_of(node, sep: str = " ") -> str:
    return " ".join(node.get_text(sep).split()) if node is not None else ""


def get_page(source, ctx, url: str | None = None) -> str:
    return ctx.session.get(url or source.url or source.page).text


def events_from_when(when_text: str, ctx, *, title: str, url: str | None, description: str | None = None,
                     location: str | None = None, source_id: str | None = None, **price) -> list[RawEvent]:
    """One RawEvent per occurrence described by when_text."""
    out = []
    for w in parse_when(when_text, ctx.now.date()):
        sid = f"{source_id}@{w.start.isoformat()}" if source_id else None
        out.append(RawEvent(source_id=sid, title=title, start=w.start, end=w.end, url=url,
                            description=description, location=location, **price))
    return out
