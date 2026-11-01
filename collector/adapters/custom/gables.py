"""Coral Gables Art Cinema: the "Coming soon" block on its calendar page.

Each .feed-movie block has the film title, a date like "fri. nov, 6" and a time; links
go to the Agile Ticketing page for that screening. This covers the special screenings
the cinema features there, not its full daily schedule (see README)."""
from __future__ import annotations

import html as htmllib
import re

from .common import events_from_when, get_page, soup, text_of


def fetch(source, ctx) -> str:
    return get_page(source, ctx)


def parse(payload: str, source, ctx):
    out = []
    for block in soup(payload).select(".feed-movie"):
        title = text_of(block.find("h2"))
        infos = [text_of(p) for p in block.select("p.home-cm-info")]
        link = block.find("a")
        if not title or not infos:
            continue
        when = " ".join(infos)
        when = re.sub(r"\b([a-z]{3,9})\.?,\s*(\d{1,2})\b", r"\1 \2", when, flags=re.I)  # "nov, 6" -> "nov 6"
        url = htmllib.unescape(link.get("href")) if link else source.page
        out += events_from_when(when, ctx, title=title, url=url, source_id=url, location=source.location)
    return out
