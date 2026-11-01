"""Event pages as the source of dates: list the event pages, open each, read date and time.

For hosts whose listings carry no dates (WordPress event types without date fields, or
listing pages without dates). Configured with `params`:

    wp_endpoint: https://example.org/wp-json/wp/v2/event   # event links from WordPress, or
    link_pattern: "/event/[^/]+/?$"                         # links on the listing page (source.page)
    query: {location: 20709}                                # extra WordPress query (optional)
    max: 25                                                 # pages opened per run
    title: h1                                               # title selector on the event page
    date: "..."                                             # date selector (optional)

Without a date selector, the page's text is scanned for the first full date (with a
year), and the first time or time range near it.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from ...normalize import RawEvent
from .common import get_page, soup, text_of
from .whenparse import parse_when

FULL_DATE = re.compile(
    r"\b(?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+)?"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b", re.I)
TIMEISH = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)", re.I)


def event_links(source, ctx) -> list[str]:
    p = source.params
    limit = int(p.get("max", 25))
    if p.get("wp_endpoint"):
        items = ctx.session.get(p["wp_endpoint"], params={"per_page": limit, **(p.get("query") or {})}).json()
        return [it["link"] for it in items if isinstance(it, dict) and it.get("link")][:limit]
    html = get_page(source, ctx)
    pat = re.compile(p["link_pattern"])
    links = []
    for href in re.findall(r'href="([^"#]+)"', html):
        url = urljoin(source.page, href)
        if pat.search(url) and url not in links:
            links.append(url)
    return links[:limit]


def fetch(source, ctx):
    pages = {}
    for url in event_links(source, ctx):
        try:
            pages[url] = ctx.session.get(url).text
        except Exception:  # noqa: BLE001 - one missing page shouldn't sink the source
            continue
    return pages


def when_text(page, p) -> str:
    if p.get("date"):
        return " ".join(text_of(n) for n in page.select(p["date"]))
    lines = [ln.strip() for ln in page.get_text("\n").split("\n") if ln.strip()]
    first = ""
    for i, ln in enumerate(lines):
        m = FULL_DATE.search(ln)
        if not m:
            continue
        rest = ln[m.end():]
        if TIMEISH.search(rest):
            return f"{m.group(0)} {rest}"
        for nxt in lines[i + 1:i + 6]:
            if TIMEISH.search(nxt) and len(nxt) < 80:
                return f"{m.group(0)} {nxt}"  # prefer a date that has a time next to it
        first = first or m.group(0)
    return first
    return ""


def page_title(page) -> str:
    """og:title or <title>, without a trailing " - Site Name"."""
    meta = page.find("meta", attrs={"property": "og:title"})
    t = (meta.get("content") if meta else None) or text_of(page.find("title"))
    return re.split(r"\s+[-|–]\s+(?=[^-|–]+$)", t or "")[0].strip()


def parse(payload, source, ctx):
    p = source.params
    out = []
    for url, html in payload.items():
        page = soup(html)
        for t in page(["script", "style", "noscript", "footer", "nav"]):
            t.decompose()
        title = text_of(page.select_one(p.get("title", "h1"))) or page_title(page)
        text = when_text(page, p)
        if not title or not text:
            continue
        for w in parse_when(text, ctx.now.date())[:1]:
            out.append(RawEvent(source_id=url, title=title, start=w.start, end=w.end, url=url,
                                location=source.location))
    return out
