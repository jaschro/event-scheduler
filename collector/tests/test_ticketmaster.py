"""Ticketmaster adapter, key redaction, and dedupe against venue listings."""
import pytest

from collector.adapters import ticketmaster
from collector.dedupe import dedupe
from collector.main import redact

from .helpers import config, context, run_adapter

PAGE = [{
    "page": {"size": 200, "totalElements": 4, "totalPages": 1, "number": 0},
    "_embedded": {"events": [
        {"id": "TM1", "type": "event", "name": "Common with Nu Deco Ensemble", "url": "https://www.ticketmaster.com/e/TM1",
         "dates": {"start": {"localDate": "2026-11-12", "localTime": "20:00:00", "dateTime": "2026-11-13T01:00:00Z"},
                   "status": {"code": "onsale"}},
         "classifications": [{"segment": {"name": "Music"}, "genre": {"name": "Hip-Hop/Rap"}}],
         "priceRanges": [{"type": "standard", "currency": "USD", "min": 45.0, "max": 125.0}],
         "_embedded": {"venues": [{"name": "Adrienne Arsht Center - Knight Concert Hall",
                                   "address": {"line1": "1300 Biscayne Blvd"}, "city": {"name": "Miami"}}]}},
        {"id": "TM2", "type": "event", "name": "Inter Miami CF vs. Orlando City", "url": "https://www.ticketmaster.com/e/TM2",
         "dates": {"start": {"localDate": "2026-11-08", "timeTBA": True}, "status": {"code": "onsale"}},
         "classifications": [{"segment": {"name": "Sports"}, "genre": {"name": "Soccer"}}],
         "_embedded": {"venues": [{"name": "Chase Stadium"}]}},
        {"id": "TM3", "type": "event", "name": "Cancelled Show",
         "dates": {"start": {"dateTime": "2026-11-09T00:00:00Z"}, "status": {"code": "cancelled"}}},
        {"id": "TM4", "type": "event", "name": "PARKING: Doja Cat",
         "dates": {"start": {"dateTime": "2026-11-12T00:00:00Z"}, "status": {"code": "onsale"}}},
        {"id": "TM1", "type": "event", "name": "Common with Nu Deco Ensemble (repeat on next page)",
         "dates": {"start": {"dateTime": "2026-11-13T01:00:00Z"}}},
    ]},
}]


def test_parse_events_kinds_venues_prices():
    cfg = config()
    events = run_adapter(ticketmaster, PAGE, cfg, "ticketmaster-miami")
    by = {e["title"]: e for e in events}
    assert set(by) == {"Common with Nu Deco Ensemble", "Inter Miami CF vs. Orlando City"}  # cancelled, parking, repeat dropped
    common = by["Common with Nu Deco Ensemble"]
    assert common["start"] == "2026-11-12T20:00:00-05:00"
    assert common["venue"] == "Adrienne Arsht Center - Knight Concert Hall"
    assert common["kind"] == "music" and common["location"] == "1300 Biscayne Blvd, Miami"
    assert common["price"] == {"free": False, "min": 45.0, "text": "$45 – $125"}
    soccer = by["Inter Miami CF vs. Orlando City"]
    assert soccer["all_day"] is True and soccer["kind"] == "sports" and soccer["venue"] == "Chase Stadium"


def test_missing_key_is_not_configured():
    from collector.adapters.base import SourceNotConfigured

    cfg = config()
    src = next(s for s in cfg.sources if s.key == "ticketmaster-miami")
    with pytest.raises(SourceNotConfigured):
        ticketmaster.fetch(src, context(cfg))


def test_errors_never_carry_the_key():
    msg = "HTTPError: 401 for url: https://app.ticketmaster.com/discovery/v2/events.json?apikey=SECRET123&latlong=1"
    out = redact(msg, {"TICKETMASTER_API_KEY": "SECRET123"})
    assert "SECRET123" not in out and "apikey=***" in out


def test_venue_listing_wins_and_borrows_ticketmaster_time():
    cfg = config()
    sources = {s.key: s for s in cfg.sources}
    tm = run_adapter(ticketmaster, PAGE, cfg, "ticketmaster-miami")
    venue = dict(tm[0], id="arsht1", source="arsht", venue="Arsht Center", all_day=True,
                 start="2026-11-12T00:00:00-05:00", end="2026-11-13T00:00:00-05:00",
                 title="Common With Nu Deco Ensemble", url="https://www.miamiandbeaches.com/event/common/1",
                 also_listed_by=[], price={"free": None, "min": None, "text": None})
    out = dedupe([venue] + tm, sources)
    common = [e for e in out if "nu deco" in e["title"].lower()]
    assert len(common) == 1
    winner = common[0]
    assert winner["source"] == "arsht" and winner["also_listed_by"] == ["ticketmaster-miami"]
    assert winner["all_day"] is False and winner["start"] == "2026-11-12T20:00:00-05:00"  # time borrowed
    assert winner["price"]["min"] == 45.0  # gap filled
