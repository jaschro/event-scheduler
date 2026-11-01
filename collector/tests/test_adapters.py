import json

from collector.adapters import eventbrite, ics

from .helpers import FIXTURES, check_expected, config, run_adapter


def test_ics_sample():
    cfg = config()
    payload = (FIXTURES / "luma_sample.ics").read_text(encoding="utf-8")
    events = run_adapter(ics, payload, cfg, "hello-miami")
    check_expected("luma_sample", events)

    titles = [e["title"] for e in events]
    # Dropped: already ended, cancelled, beyond the 14-day window.
    assert "Breakfast Already Over" not in titles
    assert "Cancelled Meetup" not in titles
    assert "Too Far Ahead" not in titles
    # Recurring event expanded, with the 11 Nov override applied.
    hack = [e for e in events if e["title"].startswith("Hack Night")]
    assert [(e["title"], e["start"]) for e in hack] == [
        ("Hack Night", "2026-11-04T18:30:00-05:00"),
        ("Hack Night: Demo Day", "2026-11-11T19:00:00-05:00"),
    ]
    assert len({e["id"] for e in events}) == len(events)
    by_title = {e["title"]: e for e in events}
    # UTC converted to Eastern; HTML stripped; script removed; link pulled from description.
    mixer = by_title["AI & Startups Mixer"]
    assert mixer["start"] == "2026-11-06T18:00:00-05:00"
    assert "<" not in mixer["description"] and "alert" not in mixer["description"]
    assert mixer["url"] == "https://luma.com/ai-mixer"
    # Floating time gets the city zone.
    assert by_title["Morning Coffee Chat"]["start"] == "2026-11-07T10:00:00-05:00"
    # All-day and multi-day.
    assert by_title["Open Studios Day"]["all_day"] is True
    assert by_title["Art Weekend"]["end"] == "2026-11-17T00:00:00-05:00"
    # Unsafe link replaced by the source page.
    assert by_title["Sketchy Link Event"]["url"] == "https://luma.com/hello_miami"
    assert "Lunch Talk In Progress" in titles


def test_eventbrite_sample():
    cfg = config()
    payload = json.loads((FIXTURES / "eventbrite_sample.json").read_text(encoding="utf-8"))
    events = run_adapter(eventbrite, payload, cfg, "el-carajo")
    check_expected("eventbrite_sample", events)

    assert [e["title"] for e in events] == ["Truffle & Barolo Dinner", "Full Moon Beach Yoga"]
    dinner, yoga = events
    assert dinner["start"] == "2026-11-05T19:30:00-05:00"
    assert dinner["price"] == {"free": False, "min": 150.0, "text": "$150.00 – $185.00"}
    assert dinner["location"] == "El Carajo, 2465 SW 17th Ave, Miami, FL 33145"
    assert yoga["price"] == {"free": True, "min": 0.0, "text": "Free (sold out)"}
    assert yoga["description"] == "Bring a towel."
