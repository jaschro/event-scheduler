"""Step 4 readers: each parses a saved copy of the real page (fixtures/pages/)
and is compared with its expected output (UPDATE_EXPECTED=1 to regenerate)."""
import json
from datetime import date

from collector.adapters import custom, jsonld, tribe
from collector.adapters.custom.whenparse import parse_when

from .helpers import FIXTURES, check_expected, config, run_adapter

PAGES = FIXTURES / "pages"


def page(name):
    return (PAGES / name).read_text(encoding="utf-8")


def summary(events):
    return [(e["start"], e["end"], e["title"]) for e in events]


def test_whenparse_patterns():
    today = date(2026, 11, 1)

    def p(text):
        return [(str(w.start), str(w.end)) for w in parse_when(text, today)]

    assert p("Saturday, Nov. 7, 2026 10:30 a.m. - 12:30 p.m.") == [("2026-11-07 10:30:00", "2026-11-07 12:30:00")]
    assert p("Thursdays 6 - 8:30 p.m. Oct. 29 - Nov. 19, 2026")[1] == ("2026-11-05 18:00:00", "2026-11-05 20:30:00")
    assert len(p("Thursdays 6 - 8:30 p.m. Oct. 29 - Nov. 19, 2026")) == 4
    assert p("Tuesdays 10 a.m. - 1 p.m. Dec. 8 & 15, 2026") == [
        ("2026-12-08 10:00:00", "2026-12-08 13:00:00"), ("2026-12-15 10:00:00", "2026-12-15 13:00:00")]
    assert p("Thu, Feb 18 | 7:30 PM - 9:30 PM") == [("2027-02-18 19:30:00", "2027-02-18 21:30:00")]
    assert p("NOV 5–29, 2026") == [("2026-11-05", "2026-11-30")]
    assert p("Tuesday, November 3, 2026 9:30 PM 10:30 PM") == [("2026-11-03 21:30:00", "2026-11-03 22:30:00")]
    assert p("Dec 28 - Jan 3, 2027") == [("2026-12-28", "2027-01-04")]
    assert p("Friday, November 6, 2026 at 7:30 PM") == [("2026-11-06 19:30:00", "None")]
    assert p("Thursday, Nov. 12, 2026 7–9 p.m.") == [("2026-11-12 19:00:00", "2026-11-12 21:00:00")]


def test_jsonld_detail_page():
    from .helpers import context

    cfg = config()
    src = next(s for s in cfg.sources if s.key == "ica-miami")
    found = jsonld.find_events(page("ica_detail.html"))
    assert len(found) == 1 and found[0]["@type"] == "Event"
    raw = jsonld.parse([("https://icamiami.org/calendar/x/", page("ica_detail.html"))], src, context(cfg))
    assert len(raw) == 1
    assert raw[0].title == "Sheroanawe Hakihiiwe Opening"
    assert raw[0].start.isoformat().startswith("2026-11-19T")
    assert raw[0].location.startswith("Institute of Contemporary Art, Miami")


def test_tribe_api_shape():
    cfg = config()
    payload = [{"events": [
        {"id": 7, "status": "publish", "title": "Gallery Talk &amp; Tour", "all_day": False,
         "start_date": "2026-11-05 18:00:00", "utc_start_date": "2026-11-05 23:00:00",
         "end_date": "2026-11-05 19:30:00", "utc_end_date": "2026-11-06 00:30:00",
         "url": "https://example.org/event/talk/", "description": "<p>Talk</p>", "cost": "Free",
         "cost_details": {"values": ["0"]}, "venue": {"venue": "Main Hall", "address": "1 Art St", "city": "Miami"}},
        {"id": 8, "status": "publish", "title": "Open Studios", "all_day": True,
         "start_date": "2026-11-07 00:00:00", "end_date": "2026-11-08 23:59:59", "url": "https://example.org/event/open/"},
    ], "next_rest_url": None}]
    events = run_adapter(tribe, payload, cfg, "ica-miami")
    assert summary(events) == [
        ("2026-11-05T18:00:00-05:00", "2026-11-05T19:30:00-05:00", "Gallery Talk & Tour"),
        ("2026-11-07T00:00:00-05:00", "2026-11-09T00:00:00-05:00", "Open Studios"),
    ]
    assert events[0]["price"] == {"free": True, "min": 0.0, "text": "Free"}
    assert events[0]["location"] == "Main Hall, 1 Art St, Miami"


def test_ica_listing_with_detail_fallback():
    cfg = config()
    payload = {"listing": page("ica_listing.html"), "details": {}}
    events = run_adapter(custom, payload, cfg, "ica-miami")
    assert all(e["url"].startswith("https://icamiami.org/calendar/") for e in events)
    assert not any("Saturday Art Prep" in e["title"] for e in events)  # enrolment deadline skipped
    check_expected("ica_listing", events)


def test_oolite():
    cfg = config()
    events = run_adapter(custom, page("oolite.html"), cfg, "oolite")
    screen = [e for e in events if e["title"] == "Four-Color Screen Printing"]
    assert [e["start"] for e in screen] == ["2026-11-05T18:00:00-05:00", "2026-11-12T18:00:00-05:00",
                                            "2026-11-19T18:00:00-05:00"][: len(screen)]
    check_expected("oolite", events)


def test_rubell_stale_page_gives_nothing_in_window():
    cfg = config()
    assert run_adapter(custom, page("rubell.html"), cfg, "rubell") == []
    src = next(s for s in cfg.sources if s.key == "rubell")
    from .helpers import context
    raw = custom.parse(page("rubell.html"), src, context(cfg))
    assert [r.title for r in raw][:2] == ["The Art of Looking: Third Member Sketch Series",
                                          "Family Art Studio: School Supply Decor Workshop"]


def test_ocinema():
    cfg = config()
    events = run_adapter(custom, page("ocinema.html"), cfg, "o-cinema")
    assert events and all(e["venue"] == "O Cinema South Beach" for e in events)
    assert all(e["url"].startswith("https://www.o-cinema.org/events/") for e in events)
    check_expected("ocinema", events)


def test_spektrix_performances():
    cfg = config()
    payload = json.loads(page("spektrix.json"))
    events = run_adapter(custom, payload, cfg, "miami-new-drama")
    assert {e["title"] for e in events} == {"Gandhi and the Jew"}
    assert events[0]["start"] == "2026-11-05T20:00:00-05:00"
    check_expected("spektrix", events)


def test_mbjcc_sitemap_and_event_page():
    from collector.adapters.custom.mbjcc import event_urls

    assert len(event_urls(page("mbjcc_sitemap.xml"))) == 10
    cfg = config()
    payload = {"sitemap": page("mbjcc_sitemap.xml"),
               "pages": {"https://mbjcc.org/events/mega-game-night/": page("mbjcc_event.html")}}
    events = run_adapter(custom, payload, cfg, "mbjcc")
    assert summary(events) == [("2026-11-05T19:00:00-05:00", "2026-11-05T23:00:00-05:00", "Mega Game Night")]
    assert events[0]["price"]["min"] == 75.0


def test_nws_listing_and_detail_time():
    cfg = config()
    detail = "https://www.nws.edu/tickets/concerts-and-events/2026-27-season/music-in-motion/"
    payload = {"listing": page("nws_listing.html"), "details": {detail: page("nws_detail.html")}}
    events = run_adapter(custom, payload, cfg, "nws")
    motion = next(e for e in events if e["title"] == "Music in Motion")
    assert motion["start"] == "2026-11-06T19:30:00-05:00" and not motion["all_day"]
    check_expected("nws", events)


def test_squarespace_events():
    cfg = config()
    events = run_adapter(custom, json.loads(page("squarespace.json")), cfg, "mb-botanical")
    assert events and all(e["url"].startswith("https://www.mbgarden.org/calendar/") for e in events)
    check_expected("squarespace", events)
