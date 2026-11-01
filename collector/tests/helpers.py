import json
import os
from datetime import datetime, timezone
from pathlib import Path

from collector.adapters.base import Context
from collector.config import City, Source
from collector.main import make_context, process_payload
from collector.config import load_config

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]
# Fixed "now" for every adapter test: Tue 3 Nov 2026, 12:00 Eastern.
NOW = datetime(2026, 11, 3, 17, 0, tzinfo=timezone.utc)
FETCHED_AT = NOW.isoformat(timespec="seconds")


def config():
    return load_config(ROOT / "sources.yaml")


def context(cfg, city="miami") -> Context:
    return make_context(cfg, city, NOW, session=None, secrets={})


def source(cfg, key) -> Source:
    return next(s for s in cfg.sources if s.key == key)


def run_adapter(adapter, payload, cfg, key):
    src = source(cfg, key)
    return process_payload(adapter, payload, src, context(cfg, src.city), cfg, FETCHED_AT)


def check_expected(name, actual):
    """Compare with fixtures/<name>.expected.json; UPDATE_EXPECTED=1 rewrites it."""
    path = FIXTURES / f"{name}.expected.json"
    if os.environ.get("UPDATE_EXPECTED") == "1":
        path.write_text(json.dumps(actual, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert actual == expected
