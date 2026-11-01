"""New World Symphony: the concerts list is built by script (it appears only after the
cookie banner is accepted), so it is rendered with Playwright. Each listing gives a date;
the concert's own page (plain HTML) gives the time, e.g. "Friday, November 6, 2026 at 7:30 PM"."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from .common import events_from_when, render_page, soup, text_of
from .whenparse import parse_when

TIME_LINE = re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\s+at\s+\d{1,2}:\d{2}\s*[AP]M", re.I)


def items(listing_html: str, base: str):
    for a in soup(listing_html).select("a.contenthighlight-linked"):
        title = text_of(a.select_one(".contenthighlight-title"))
        date = text_of(a.select_one(".preheading"))
        if title and date:
            yield title, urljoin(base, a.get("href")), date


def fetch(source, ctx):
    listing = render_page(source.page, ctx)
    details = {}
    for _title, url, date in items(listing, source.page):
        whens = parse_when(date, ctx.now.date())
        in_window = any(ctx.window_start.date() <= (w.start.date() if hasattr(w.start, "date") else w.start)
                        < ctx.window_end.date() for w in whens)
        if in_window and url not in details:
            try:
                details[url] = ctx.session.get(url).text
            except Exception:  # noqa: BLE001
                details[url] = ""
    return {"listing": listing, "details": details}


def parse(payload, source, ctx):
    out = []
    for title, url, date in items(payload["listing"], source.page):
        page = payload["details"].get(url) or ""
        times = TIME_LINE.findall(re.sub(r"<[^>]+>", " ", page)) if page else []
        when = " ".join(dict.fromkeys(times)) if times else date
        if len(set(times)) > 1:  # several performances listed on the concert page
            for t in dict.fromkeys(times):
                out += events_from_when(t, ctx, title=title, url=url, source_id=url, location=source.location)
            continue
        out += events_from_when(when, ctx, title=title, url=url, source_id=url, location=source.location)
    return out
