"""ICA Miami calendar: listing tiles give date + link; each event page has schema.org Event JSON-LD
with the start time. Only events dated inside the window are opened (about 1 request/second)."""
from __future__ import annotations

from ..jsonld import find_events
from ..jsonld import parse as jsonld_parse
from .common import events_from_when, get_page, soup, text_of
from .whenparse import parse_when


def tiles(listing_html: str, ctx):
    for art in soup(listing_html).select("article.calendar-tile"):
        date_el = art.select_one(".cal-date")
        link = art.select_one("a.thumbnail__link")
        title = text_of(art.select_one(".cal-title"))
        if date_el is None or link is None or not title:
            continue
        label = text_of(date_el)
        if "deadline" in label.lower():
            continue  # enrolment deadlines, not events
        whens = parse_when(label, ctx.now.date())
        yield title, link.get("href"), label, whens


def fetch(source, ctx):
    listing = get_page(source, ctx)
    details = {}
    for _title, href, _label, whens in tiles(listing, ctx):
        if any(ctx.window_start.date() <= (w.start if not hasattr(w.start, "date") else w.start.date())
               < ctx.window_end.date() for w in whens) and href not in details:
            try:
                details[href] = ctx.session.get(href).text
            except Exception:  # noqa: BLE001 - fall back to the listing date
                details[href] = ""
    return {"listing": listing, "details": details}


def parse(payload, source, ctx):
    out = []
    for title, href, label, _whens in tiles(payload["listing"], ctx):
        page = payload["details"].get(href) or ""
        found = jsonld_parse([(href, page)], source, ctx) if page and find_events(page) else []
        if found:
            for ev in found:
                ev.url = href
                ev.title = ev.title or title
                ev.source_id = href
            out += found
        else:
            out += events_from_when(label, ctx, title=title, url=href, source_id=href)
    return out
