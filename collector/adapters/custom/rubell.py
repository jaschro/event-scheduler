"""Rubell Museum member events: <h3>title</h3><h5>date</h5><p>…</p> blocks under "Upcoming Events"."""
from __future__ import annotations

from .common import events_from_when, get_page, soup, text_of


def fetch(source, ctx) -> str:
    return get_page(source, ctx)


def parse(payload: str, source, ctx):
    page = soup(payload)
    start = next((h for h in page.find_all(["h1", "h2"]) if "upcoming events" in text_of(h).lower()), None)
    if start is None:
        return []
    out = []
    for h3 in start.find_all_next("h3"):
        heading = h3.find_previous(["h1", "h2"])
        if heading is not None and "recent events" in text_of(heading).lower():
            break
        title = text_of(h3)
        h5 = h3.find_next_sibling("h5")
        if not title or h5 is None:
            continue
        paras = []
        for sib in h5.find_next_siblings():
            if sib.name in ("h3", "h5"):
                break
            if sib.name == "p" and text_of(sib):
                paras.append(text_of(sib))
        link = h3.find("a")
        out += events_from_when(text_of(h5), ctx, title=title, url=link.get("href") if link else None,
                                description="\n".join(paras), source_id=link.get("href") if link else title,
                                location="Rubell Museum, 1100 NW 23rd St, Miami")
    return out
