"""General listing-page reader, configured per source in sources.yaml (`params`).

It starts from each date element, climbs to the event's container, and reads the title,
link and any separate time from there:

    when:   CSS selector for the date (or date + time) element          (required)
    item:   selector the container matches (closest ancestor), or
    item_up: how many parents to climb from the date element instead
            (default: the nearest ancestor that contains the title)
    time_next: true when the time is in the element right after the date
    title:  selector for the title inside the container                 (required)
    link:   selector for the link inside the container (default: the title's link,
            the container itself if it is a link, else its first link)
    time:   selector for a separate time element inside the container   (optional)
    price:  selector for a price line inside the container              (optional)

Per-day blocks (a day heading with several events under it) use instead:
    item: <day block>, when: <day heading>, events: <title of each event>, time: <time
    element following each event title>.
Dates without a year get the nearest sensible year; without a time they become all-day.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

import soupsieve

from ...normalize import RawEvent
from .common import get_page, soup, text_of
from .whenparse import parse_when

PRICE_RE = re.compile(r"\$\s?(\d+(?:\.\d\d)?)")


def fetch(source, ctx) -> str:
    if source.method == "browser":  # listing built by script: render it first
        from .common import render_page

        return render_page(source.url or source.page, ctx, wait_ms=int(source.params.get("wait_ms", 6000)))
    return get_page(source, ctx)


def _container(node, p):
    if p.get("item"):
        for anc in node.parents:
            if getattr(anc, "name", None) and soupsieve.match(p["item"], anc):
                return anc
        return None
    if p.get("item_up") is not None:
        el = node
        for _ in range(int(p["item_up"])):
            el = el.parent if el is not None else None
        return el
    # Default: the nearest ancestor that also contains the title.
    for anc in node.parents:
        if getattr(anc, "name", None) and anc.select_one(p["title"]) is not None:
            return anc
    return None


def _link(box, title_el, p, base):
    a = None
    if p.get("link"):
        a = box.select_one(p["link"])
    if a is None and title_el is not None:
        a = title_el if title_el.name == "a" else title_el.find("a", href=True)
    if a is None and box.name == "a":
        a = box
    if a is None:
        a = box.find("a", href=True)
    if a is None:
        a = box.find_parent("a", href=True)  # the whole card is the link
    href = a.get("href") if a is not None else None
    return urljoin(base, href) if href and not href.startswith(("#", "mailto:", "javascript:")) else base


def _events(when_text, ctx, *, title, url, location, desc=None, price_text=None):
    out = []
    price = PRICE_RE.search(price_text or "")
    for w in parse_when(when_text, ctx.now.date()):
        out.append(RawEvent(
            source_id=f"{url}@{w.start.isoformat()}" if url else None,
            title=title, start=w.start, end=w.end, url=url, location=location, description=desc,
            price_min=float(price.group(1)) if price else None,
            price_free=True if price_text and re.search(r"\bfree\b", price_text, re.I) else None,
            price_text=" ".join(price_text.split()) if price_text else None,
        ))
    return out


def parse(payload: str, source, ctx):
    p = source.params
    page = soup(payload)
    base = source.url or source.page
    out, seen = [], set()

    if p.get("events"):  # per-day blocks
        for block in page.select(p["item"]):
            day = text_of(block.select_one(p["when"]))
            for head in block.select(p["events"]):
                title = text_of(head)
                t = head.find_next(lambda tag: soupsieve.match(p["time"], tag)) if p.get("time") else None
                url = _link(head, head, {}, base)
                key = (title, day, text_of(t))
                if not title or key in seen:
                    continue
                seen.add(key)
                out += _events(f"{day} {text_of(t)}", ctx, title=title, url=url, location=source.location)
        return out

    for node in page.select(p["when"]):
        box = _container(node, p)
        if box is None:
            continue
        title_el = box.select_one(p["title"])
        title = text_of(title_el)
        when = text_of(node)
        if p.get("time_next"):  # time printed in the next element, e.g. "Mon, Nov 9, 2026" / "6–9 PM"
            nxt = node.find_next_sibling()
            when = f"{when} {text_of(nxt)}"
        if p.get("time"):
            when = f"{when} {text_of(box.select_one(p['time']))}"
        key = (title, when)
        if not title or key in seen:
            continue
        seen.add(key)
        url = _link(box, title_el, p, base)
        price = text_of(box.select_one(p["price"])) if p.get("price") else None
        out += _events(when, ctx, title=title, url=url, location=source.location, price_text=price)
    return drop_dateonly_twins(out)


def drop_dateonly_twins(events):
    """A page may show one event twice (a featured banner with only a date, a card with the
    time): when the same title and day also appear with a time, drop the date-only copy."""
    from datetime import datetime

    timed = {(e.title.casefold(), e.start.date()) for e in events if isinstance(e.start, datetime)}
    return [e for e in events if isinstance(e.start, datetime) or (e.title.casefold(), e.start) not in timed]
