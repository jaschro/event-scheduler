"""Miami Beach JCC: the listing shows only a few events ("Load More" is a client action),
so the event pages are found through the site's Yoast sitemap, and each page gives
Date ("Thu, Nov 5") and Time ("7:00 pm – 11:00 pm"). Year is inferred."""
from __future__ import annotations

import re

from .common import events_from_when, soup, text_of

SITEMAP = "https://mbjcc.org/sitemap/post-sitemap.xml"
MAX_PAGES = 40


def event_urls(sitemap_xml: str) -> list[str]:
    return [u for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap_xml) if "/events/" in u][:MAX_PAGES]


def fetch(source, ctx):
    sitemap = ctx.session.get(SITEMAP).text
    pages = {}
    for url in event_urls(sitemap):
        try:
            pages[url] = ctx.session.get(url).text
        except Exception:  # noqa: BLE001 - a removed event page shouldn't sink the source
            continue
    return {"sitemap": sitemap, "pages": pages}


def _first(page, prefix):
    return page.select_one(f'[class^="{prefix}"], [class*=" {prefix}"]')


def parse(payload, source, ctx):
    out = []
    for url, html in payload["pages"].items():
        page = soup(html)
        title = text_of(_first(page, "styles_headline"))
        date_el = _first(page, "styles_eventDate")
        time_el = _first(page, "styles_eventTime")
        if not title or date_el is None:
            continue
        when = f"{text_of(date_el.find('p'))} {text_of(time_el.find('p')) if time_el else ''}"
        copy = _first(page, "styles_copy")
        desc = "\n".join(text_of(p) for p in copy.find_all("p")) if copy else None
        price = re.search(r"\$\s?(\d+(?:\.\d\d)?)", desc or "")
        out += events_from_when(when, ctx, title=title, url=url, description=desc, source_id=url,
                                location="Miami Beach JCC, 4221 Pine Tree Dr, Miami Beach",
                                price_min=float(price.group(1)) if price else None,
                                price_text=f"${price.group(1)}" if price else None)
    return out
