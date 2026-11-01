"""O Cinema South Beach: Webflow listing; each film lists its showtimes (date + time) in the page HTML.

The probe found the showtimes already in the server HTML (180 slots for 9 films),
so no browser is needed. Empty Webflow slots are skipped; only screenings at the
South Beach venue are kept.
"""
from __future__ import annotations

from urllib.parse import urljoin

from .common import events_from_when, get_page, soup, text_of

VENUE_MATCH = "south beach"


def fetch(source, ctx) -> str:
    return get_page(source, ctx)


def parse(payload: str, source, ctx):
    out = []
    for item in soup(payload).select(".screenings_item"):
        title_el = item.select_one(".item_details-title")
        title = text_of(title_el)
        loc = text_of(item.select_one(".item_details-location"))
        if not title or (loc and VENUE_MATCH not in loc.lower()):
            continue
        info = urljoin(source.page, title_el.get("href")) if title_el and title_el.get("href") else source.page
        tickets = item.select_one('a[href*="agileticketing"]')
        seen = set()
        for st in item.select(".item_details_showtime"):
            d = text_of(st.select_one(".item_details-date"))
            t = text_of(st.select_one(".item_details-time"))
            if not d or not t or (d, t) in seen:
                continue
            seen.add((d, t))
            out += events_from_when(f"{d} {t}", ctx, title=title, url=info, location=loc or None,
                                    source_id=info,
                                    description=f"Tickets: {tickets['href']}" if tickets else None)
    return out
