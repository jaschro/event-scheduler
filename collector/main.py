"""Run every source, merge, and write data/events.json and data/status.json.

    python -m collector.main [--config sources.yaml] [--data data] [--only KEY ...]

Exit code 1 only when every attempted source failed (SPEC.md section 5).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .adapters import ADAPTERS
from .adapters.base import Context, SourceNotConfigured
from .config import Config, Source, load_config
from .dedupe import dedupe
from .normalize import build_event, in_window, passes_filter
from .polite import PoliteSession

log = logging.getLogger("collector")

SCHEMA_VERSION = 1
# Fields that change on every run; ignored when deciding whether the data changed.
VOLATILE_TOP = {"generated_at"}
VOLATILE_EVENT = {"fetched_at"}
VOLATILE_STATUS = {"last_success", "last_run"}



def make_context(cfg: Config, city_key: str, now_utc: datetime, session, secrets) -> Context:
    city = cfg.cities[city_key]
    now = now_utc.astimezone(city.tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = (start + timedelta(days=cfg.settings["days_ahead"])).date()
    end = datetime.combine(end_date, datetime.min.time(), tzinfo=city.tz)
    return Context(city=city, now=now, window_start=start, window_end=end, session=session, secrets=secrets)


def collect_source(src: Source, ctx: Context, cfg: Config, fetched_at: str) -> list[dict[str, Any]]:
    adapter = ADAPTERS[src.method]
    payload = adapter.fetch(src, ctx)
    return process_payload(adapter, payload, src, ctx, cfg, fetched_at)


def process_payload(adapter, payload, src: Source, ctx: Context, cfg: Config, fetched_at: str) -> list[dict[str, Any]]:
    hours = cfg.settings["default_duration_hours"]
    events = []
    for raw in adapter.parse(payload, src, ctx):
        ev = build_event(raw, source=src, city=ctx.city, fetched_at=fetched_at)
        if ev and in_window(ev, ctx.now, ctx.window_end, hours) and passes_filter(ev, src.filter):
            events.append(ev)
    events.sort(key=lambda e: (datetime.fromisoformat(e["start"]), e["title"], e["id"]))
    return events


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def previous_events_for(prev: dict[str, Any], key: str, ctx: Context, cfg: Config) -> list[dict[str, Any]]:
    """Last good run's events from a source that failed now, still in the window."""
    hours = cfg.settings["default_duration_hours"]
    kept = []
    for ev in prev.get("events") or []:
        if ev.get("source") == key and in_window(ev, ctx.now, ctx.window_end, hours):
            ev = {**ev, "also_listed_by": [], "price": dict(ev.get("price") or {})}
            kept.append(ev)
    return kept


def _strip(obj: Any, volatile: set[str]) -> Any:
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if k not in volatile}
    return obj


def stable_events(doc: dict[str, Any]) -> Any:
    top = _strip(doc, VOLATILE_TOP)
    return {**top, "events": [_strip(e, VOLATILE_EVENT) for e in doc.get("events") or []]}


def stable_status(doc: dict[str, Any]) -> Any:
    top = _strip(doc, VOLATILE_TOP)
    return {**top, "sources": {k: _strip(v, VOLATILE_STATUS) for k, v in (doc.get("sources") or {}).items()}}


def keep_old_fetched_at(events: list[dict[str, Any]], prev: dict[str, Any]) -> None:
    """An unchanged event keeps its earlier fetched_at, so unchanged data diffs as unchanged."""
    old = {e["id"]: e for e in prev.get("events") or [] if "id" in e}
    for ev in events:
        o = old.get(ev["id"])
        if o and _strip(o, VOLATILE_EVENT) == _strip(ev, VOLATILE_EVENT):
            ev["fetched_at"] = o.get("fetched_at", ev["fetched_at"])


def write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def run(
    cfg: Config,
    data_dir: Path,
    *,
    only: set[str] | None = None,
    now_utc: datetime | None = None,
    session=None,
    secrets: dict[str, str] | None = None,
) -> int:
    now_utc = now_utc or datetime.now(timezone.utc)
    fetched_at = now_utc.isoformat(timespec="seconds")
    secrets = secrets if secrets is not None else {k: v for k, v in os.environ.items() if k == "EVENTBRITE_TOKEN"}
    session = session or PoliteSession(
        cfg.settings["user_agent"],
        delay=float(cfg.settings["request_delay_seconds"]),
        timeout=float(cfg.settings["request_timeout_seconds"]),
    )
    events_path, status_path = data_dir / "events.json", data_dir / "status.json"
    prev_events, prev_status = load_json(events_path), load_json(status_path)
    prev_src_status = prev_status.get("sources") or {}

    contexts = {key: make_context(cfg, key, now_utc, session, secrets) for key in cfg.cities}
    all_events: list[dict[str, Any]] = []
    status: dict[str, dict[str, Any]] = {}
    attempted = failed = 0

    runnable = [s for s in cfg.sources if s.enabled and s.method in ADAPTERS and (not only or s.key in only)]
    timeout = float(cfg.settings["source_timeout_seconds"])
    pool = ThreadPoolExecutor(max_workers=6)
    futures = {s.key: pool.submit(collect_source, s, contexts[s.city], cfg, fetched_at) for s in runnable}

    for src in cfg.sources:
        before = prev_src_status.get(src.key, {})
        entry: dict[str, Any] = {
            "name": src.name,
            "city": src.city,
            "method": src.method,
            "last_run": fetched_at,
            "last_success": before.get("last_success"),
        }
        if src.key not in futures:
            if only and src.key not in only and src.key in prev_src_status:
                status[src.key] = before  # not part of this partial run: leave as it was
                all_events.extend(previous_events_for(prev_events, src.key, contexts[src.city], cfg))
                continue
            reason = "disabled in sources.yaml" if not src.enabled else f"no '{src.method}' adapter yet"
            entry.update(result="skipped", event_count=0, error=reason)
            status[src.key] = entry
            continue

        attempted += 1
        try:
            events = futures[src.key].result(timeout=timeout)
            all_events.extend(events)
            entry.update(result="ok", event_count=len(events), error=None, last_success=fetched_at)
            log.info("%-18s ok      %3d events", src.key, len(events))
        except Exception as exc:  # noqa: BLE001 - one source must never break the run
            failed += 1
            if isinstance(exc, FutureTimeout):
                msg = f"timed out after {timeout:.0f}s"
            elif isinstance(exc, SourceNotConfigured):
                msg = f"not configured: {exc}"
            else:
                msg = f"{type(exc).__name__}: {exc}"[:300]
                log.debug("%s", traceback.format_exc())
            kept = previous_events_for(prev_events, src.key, contexts[src.city], cfg)
            all_events.extend(kept)
            entry.update(result="failed", event_count=len(kept), error=msg)
            log.warning("%-18s FAILED  %s (kept %d from last good run)", src.key, msg, len(kept))
        status[src.key] = entry
    pool.shutdown(wait=False, cancel_futures=True)

    sources_by_key = {s.key: s for s in cfg.sources}
    merged = dedupe(all_events, sources_by_key)
    keep_old_fetched_at(merged, prev_events)

    any_ctx = next(iter(contexts.values()))
    events_doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": fetched_at,
        "window": {"start": any_ctx.window_start.date().isoformat(), "days": cfg.settings["days_ahead"]},
        "cities": [{"key": c.key, "name": c.name, "tz": c.tz.key} for c in cfg.cities.values()],
        "events": merged,
    }
    status_doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": fetched_at,
        "summary": {
            "attempted": attempted,
            "ok": attempted - failed,
            "failed": failed,
            "events": len(merged),
        },
        "sources": status,
    }

    changed = (
        stable_events(events_doc) != stable_events(prev_events)
        or stable_status(status_doc) != stable_status(prev_status)
    )
    if changed:
        write_json(events_path, events_doc)
        write_json(status_path, status_doc)
        log.info("wrote %d events from %d/%d sources", len(merged), attempted - failed, attempted)
    else:
        log.info("no changes; data files left as they were")

    if attempted and failed == attempted:
        log.error("every source failed")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(root / "sources.yaml"))
    ap.add_argument("--data", default=str(root / "data"))
    ap.add_argument("--only", nargs="*", help="run just these source keys")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config(args.config)
    return run(cfg, Path(args.data), only=set(args.only) if args.only else None)


if __name__ == "__main__":
    sys.exit(main())
