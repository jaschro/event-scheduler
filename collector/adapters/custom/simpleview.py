"""Events listed for a venue on the Greater Miami tourism site (miamiandbeaches.com, Simpleview CMS).

Used for the Arsht Center, whose own calendar blocks automated readers. Each event card
has a title, a date and a link; the event page is opened for schema.org JSON-LD times
when the date falls in the window, otherwise the listing date is used as an all-day item.
"Select Days - Through …" runs are listed on their next date, with the run noted."""
from __future__ import annotations

from urllib.parse import urljoin

from ..jsonld import find_events
from ..jsonld import parse as jsonld_parse
from .common import events_from_when, get_page, soup, text_of
from .whenparse import parse_when


def cards(listing_html: str, base: str, ctx):
    for art in soup(listing_html).select("article.ys-card--event"):
        link = art.find("a")
        title = text_of(art.find(["h3", "h2"]))
        if link is None or not title:
            continue
        dates = [text_of(s) for s in art.select("span[class*='ys-card__event-meta']") if text_of(s)]
        is_note = lambda d: d.lower().startswith(("select days", "daily through"))  # noqa: E731
        exact = [d for d in dates if not is_note(d)]
        note = next((d for d in dates if is_note(d)), None)
        when_text = exact[0] if exact else (dates[0] if dates else "")
        desc = text_of(art.select_one(".lh-base"))
        yield title, urljoin(base, link.get("href")), when_text, note, desc, parse_when(when_text, ctx.now.date())


def _in_window(whens, ctx):
    return any(ctx.window_start.date() <= (w.start.date() if hasattr(w.start, "date") else w.start)
               < ctx.window_end.date() for w in whens)


def fetch(source, ctx):
    listing = get_page(source, ctx)
    details = {}
    for _t, url, _w, _n, _d, whens in cards(listing, source.page, ctx):
        if _in_window(whens, ctx) and url not in details:
            try:
                details[url] = ctx.session.get(url).text
            except Exception:  # noqa: BLE001
                details[url] = ""
    return {"listing": listing, "details": details}


def parse(payload, source, ctx):
    out = []
    for title, url, when_text, note, desc, _whens in cards(payload["listing"], source.page, ctx):
        description = f"{desc}\n\n{note}" if note and desc else (desc or note)
        page = payload["details"].get(url) or ""
        found = jsonld_parse([(url, page)], source, ctx) if page and find_events(page) else []
        if found:
            for ev in found:
                ev.title, ev.url, ev.source_id = title, url, url
                ev.description = ev.description or description
                ev.location = ev.location or source.location
            out += found
        else:
            out += events_from_when(when_text, ctx, title=title, url=url, description=description,
                                    source_id=url, location=source.location)
    return out
