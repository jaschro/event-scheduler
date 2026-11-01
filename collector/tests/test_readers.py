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
    # Showtimes give no end: films are assumed to run 2.5 hours (default_minutes_by_kind.film).
    from datetime import datetime, timedelta
    assert all(datetime.fromisoformat(e["end"]) - datetime.fromisoformat(e["start"]) == timedelta(minutes=150)
               for e in events)
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


def test_gables_agile_calendar_jsonld():
    cfg = config()
    url = next(s for s in cfg.sources if s.key == "gables-cinema").url
    events = run_adapter(jsonld, [(url, page("gables_agile_list.html"))], cfg, "gables-cinema")
    assert events and all(e["venue"] == "Coral Gables Art Cinema" for e in events)
    first = next(e for e in events if e["title"] == "Once Upon a Time in Harlem")
    assert first["start"] == "2026-11-06T13:15:00-05:00"
    assert first["end"] == "2026-11-06T15:45:00-05:00"  # 2.5-hour film default
    check_expected("gables", events)


def test_arsht_via_miamiandbeaches():
    cfg = config()
    payload = {"listing": page("arsht_miamiandbeaches.html"), "details": {}}
    events = run_adapter(custom, payload, cfg, "arsht")
    titles = [e["title"] for e in events]
    assert "God of Carnage" in titles and "Jobim and the Music of Brazil" in titles
    carnage = next(e for e in events if e["title"] == "God of Carnage")
    assert carnage["all_day"] and carnage["start"].startswith("2026-11-05")
    assert "Through Nov 22, 2026" in carnage["description"]
    check_expected("arsht", events)


def test_wprest_van_alen_acf_dates():
    from collector.adapters import wprest

    cfg = config()
    events = run_adapter(wprest, [json.loads(page("wp_vanalen.json"))], cfg, "nyc-van-alen")
    assert events and all(e["url"].startswith("https://www.vanalen.org/events/") for e in events)
    check_expected("wp_vanalen", events)


def test_wprest_pratt_event_organiser_dates():
    from collector.adapters import wprest

    cfg = config()
    events = run_adapter(wprest, [json.loads(page("wp_pratt.json"))], cfg, "nyc-pratt-arch")
    assert events and all(e["city"] == "nyc" for e in events)
    check_expected("wp_pratt", events)


def test_tribe_ny_jewish_week_keeps_category_query():
    from collector.adapters.tribe import source_query

    cfg = config()
    src = next(s for s in cfg.sources if s.key == "nyc-ny-jewish-week")
    assert source_query(src) == {"categories": "new-york"}
    events = run_adapter(tribe, [json.loads(page("tribe_nyjw.json"))], cfg, "nyc-ny-jewish-week")
    assert events
    check_expected("tribe_nyjw", events)


def test_club_free_time_jsonld():
    cfg = config()
    url = next(s for s in cfg.sources if s.key == "nyc-club-free-time").page
    events = run_adapter(jsonld, [(url, page("clubfreetime.html"))], cfg, "nyc-club-free-time")
    assert len(events) > 10
    check_expected("clubfreetime", events)


LISTING_PAGES = {
    "nyc-cooper-union-arch": "listing_cooper-union-arch.html",
    "nyc-nyu-stern": "listing_nyu-stern.html",
    "nyc-aiany": "listing_aiany.html",
    "nyc-mas": "listing_mas.html",
    "nyc-rpa": "listing_rpa.html",
    "nyc-skyscraper-museum": "listing_skyscraper-museum.html",
    "nyc-cfr": "listing_cfr.html",
    "nyc-carnegie-council": "listing_carnegie-council.html",
    "nyc-paley-center": "listing_paley-center.html",
    "nyc-cjh": "listing_cjh.html",
    "nyc-yivo": "listing_yivo.html",
}


def test_listing_reader_pages():
    """The general listing reader against each NYC host's saved page."""
    import pytest

    cfg = config()
    results = {}
    for key, name in LISTING_PAGES.items():
        events = run_adapter(custom, page(name), cfg, key)
        results[key] = events
        assert all(e["city"] == "nyc" and e["title"] for e in events), key
    # Spot checks against what the pages show.
    gct = [e for e in results["nyc-mas"] if e["title"] == "Grand Central Terminal"]
    assert "2026-11-04T11:00:00-05:00" in [e["start"] for e in gct]
    assert all(e["price"]["min"] == 15.0 for e in gct)
    assert any(e["title"].startswith("Fire and Clay") and e["start"] == "2026-11-10T18:00:00-05:00"
               for e in results["nyc-skyscraper-museum"])
    assert any(e["start"] == "2026-11-14T11:00:00-05:00" and e["end"] == "2026-11-14T16:00:00-05:00"
               for e in results["nyc-rpa"])
    assert len(results["nyc-aiany"]) >= 5
    check_expected("listing_nyc", {k: [list(t) for t in summary(v)] for k, v in results.items()})
