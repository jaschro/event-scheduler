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


def render_page(url: str, ctx, *, accept_cookies: bool = True, wait_ms: int = 4000) -> str:
    """Render a script-built page in headless Chromium (Playwright) and return its HTML.

    robots.txt and the per-host pacing are honoured by first fetching the page through
    the polite session; the browser identifies itself with the same user agent.
    """
    ctx.session.get(url)  # robots check + pacing; raises if disallowed
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=ctx.session.user_agent)
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(wait_ms)
            if accept_cookies:
                for label in ("Allow all", "Accept All", "Accept all", "Accept", "I agree", "OK"):
                    btn = page.get_by_role("button", name=label, exact=True)
                    if btn.count():
                        try:
                            btn.first.click(timeout=2000)
                            page.wait_for_timeout(wait_ms)
                            break
                        except Exception:  # noqa: BLE001
                            pass
            for _ in range(3):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(800)
            return page.content()
        finally:
            browser.close()
