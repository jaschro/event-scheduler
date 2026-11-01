"""Hand-written page readers, one module per venue (SPEC.md section 3).

A source with `method: custom` (plain HTTP) or `method: browser` (Playwright)
names its module with `reader: <module>`. Each module exposes the usual
fetch(source, ctx) -> payload and parse(payload, source, ctx) -> list[RawEvent];
tests run parse() against a saved copy of the page.
"""
from __future__ import annotations

import importlib


def reader(source):
    return importlib.import_module(f"{__name__}.{source.reader}")


def fetch(source, ctx):
    return reader(source).fetch(source, ctx)


def parse(payload, source, ctx):
    return reader(source).parse(payload, source, ctx)
