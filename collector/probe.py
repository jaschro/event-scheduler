"""Probe sources without a feed to find the cheapest working method (SPEC.md section 3).

For each source: robots.txt, the page itself, The Events Calendar REST API,
schema.org Event JSON-LD, other WordPress hints, iCal links, and (for --browser
sources) a Playwright render with the JSON responses it loads.
Everything is saved under probe/<key>/ with a summary in probe/summary.json.

    python -m collector.probe [--only KEY ...] [--out probe]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from .adapters.jsonld import find_events
from .config import load_config
from .polite import PoliteSession, RobotsDisallowed

ROOT = Path(__file__).resolve().parent.parent
BROWSER_KEYS = {"o-cinema", "gables-cinema", "nws"}
EVENT_WORDS = re.compile(r"event|exhibit|show|performance|program|calendar|film|concert", re.I)


def save(path: Path, data, binary=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    elif binary:
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


def try_get(session, url, **kw):
    try:
        r = session.get(url, **kw)
        return {"ok": True, "status": r.status_code, "url": r.url, "type": r.headers.get("content-type", ""), "resp": r}
    except RobotsDisallowed as e:
        return {"ok": False, "error": f"robots: {e}"}
    except Exception as e:  # noqa: BLE001
        resp = getattr(e, "response", None)
        return {"ok": False, "status": getattr(resp, "status_code", None), "error": f"{type(e).__name__}: {e}"[:300]}


def probe_source(src, session, out: Path, browser: bool) -> dict:
    d = out / src.key
    info: dict = {"key": src.key, "page": src.page}
    parts = urlsplit(src.page)
    origin = f"{parts.scheme}://{parts.netloc}"

    page = try_get(session, src.page)
    info["page_fetch"] = {k: v for k, v in page.items() if k != "resp"}
    html = ""
    if page["ok"]:
        html = page["resp"].text
        save(d / "page.html", html)
        evs = find_events(html)
        info["jsonld_events"] = len(evs)
        if evs:
            save(d / "jsonld.json", evs)
        info["ical_links"] = sorted(set(re.findall(r'(?:href|src)="([^"]*(?:ical|\.ics|webcal)[^"]*)"', html, re.I)))[:20]
        info["wordpress"] = "wp-content" in html or "wp-json" in html
        info["generator"] = re.findall(r'<meta name="generator" content="([^"]+)"', html)[:5]
        info["has_tribe_markup"] = "tribe-events" in html or "tribe_events" in html
        info["page_bytes"] = len(html)

    tribe = try_get(session, origin + "/wp-json/tribe/events/v1/events?per_page=50")
    info["tribe_api"] = {k: v for k, v in tribe.items() if k != "resp"}
    if tribe["ok"]:
        try:
            body = tribe["resp"].json()
            info["tribe_api"]["events"] = len(body.get("events") or [])
            info["tribe_api"]["total"] = body.get("total")
            save(d / "tribe.json", body)
        except ValueError:
            info["tribe_api"]["error"] = "not JSON"

    if info.get("wordpress") or tribe.get("status") not in (None, 404):
        types = try_get(session, origin + "/wp-json/wp/v2/types")
        if types["ok"]:
            try:
                body = types["resp"].json()
                info["wp_types"] = {k: v.get("rest_base") for k, v in body.items() if isinstance(v, dict)}
                for name, base in info["wp_types"].items():
                    if base and EVENT_WORDS.search(name + " " + base):
                        r = try_get(session, f"{origin}/wp-json/wp/v2/{base}?per_page=20")
                        if r["ok"]:
                            save(d / f"wp_{base}.json", r["resp"].text)
            except ValueError:
                pass
        ns = try_get(session, origin + "/wp-json/")
        if ns["ok"]:
            try:
                info["wp_namespaces"] = ns["resp"].json().get("namespaces")
            except ValueError:
                pass

    if browser:
        info["browser"] = render(src, d)
    return info


def render(src, d: Path) -> dict:
    from playwright.sync_api import sync_playwright

    result: dict = {"json_responses": []}
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(user_agent="EventSchedulerBot/0.1 (+https://github.com/jaschro/event-scheduler)")
        n = 0

        def on_response(resp):
            nonlocal n
            ctype = resp.headers.get("content-type", "")
            if "json" in ctype and n < 40:
                try:
                    body = resp.text()
                except Exception:  # noqa: BLE001
                    return
                n += 1
                name = f"net_{n:02d}.json"
                save(d / name, body[:400_000])
                result["json_responses"].append({"file": name, "url": resp.url[:300], "bytes": len(body)})

        page.on("response", on_response)
        try:
            page.goto(src.page, wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(3000)
            html = page.content()
            save(d / "rendered.html", html)
            result["rendered_bytes"] = len(html)
            result["jsonld_events"] = len(find_events(html))
            result["iframes"] = [f.url[:300] for f in page.frames if f.url and f.url != "about:blank"][:10]
        except Exception as e:  # noqa: BLE001
            result["error"] = f"{type(e).__name__}: {e}"[:300]
        b.close()
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", default=str(ROOT / "probe"))
    args = ap.parse_args(argv)
    cfg = load_config(ROOT / "sources.yaml")
    session = PoliteSession(cfg.settings["user_agent"], delay=1.0, timeout=30)
    out = Path(args.out)
    keys = set(args.only or [])
    summary = []
    for src in cfg.sources:
        if keys and src.key not in keys:
            continue
        if not keys and src.enabled:
            continue
        print(f"probing {src.key} ...", flush=True)
        try:
            summary.append(probe_source(src, session, out, src.key in BROWSER_KEYS))
        except Exception as e:  # noqa: BLE001
            summary.append({"key": src.key, "error": f"{type(e).__name__}: {e}"[:300]})
    save(out / "summary.json", summary)
    for s in summary:
        print(json.dumps({k: s.get(k) for k in ("key", "jsonld_events", "tribe_api", "wordpress")})[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
