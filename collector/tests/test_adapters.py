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


def test_luma_calendar_lookup():
    from collector.adapters.base import Context

    from .helpers import context

    class Resp:
        def __init__(self, data=None, text=""):
            self._data, self.text, self.encoding = data, text, "utf-8"

        def json(self):
            return self._data

    calls = []

    class Session:
        def get(self, url, **kw):
            calls.append(url)
            if "/url?url=manatech" in url:
                return Resp({"kind": "calendar", "data": {"calendar": {"api_id": "cal-AbC123", "name": "ManaTech"}}})
            if "/ics/get?entity=calendar&id=cal-AbC123" in url:
                return Resp(text="BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n")
            raise AssertionError(url)

    cfg = config()
    src = next(s for s in cfg.sources if s.key == "manatech")
    src.url, src.luma_calendar = None, "manatech"
    ctx = context(cfg)
    ctx.session = Session()
    assert ics.fetch(src, ctx).startswith("BEGIN:VCALENDAR")
    assert calls == [
        "https://api.luma.com/url?url=manatech",
        "https://api.luma.com/ics/get?entity=calendar&id=cal-AbC123",
    ]


def test_windows_time_zone_names():
    cfg = config()
    payload = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-TIMEZONE:Eastern Time (US & Canada)\r\n"
        "BEGIN:VTIMEZONE\r\nTZID:Eastern Time (US & Canada)\r\n"
        "BEGIN:STANDARD\r\nDTSTART:16010101T020000\r\nTZOFFSETFROM:-0400\r\nTZOFFSETTO:-0500\r\n"
        "RRULE:FREQ=YEARLY;BYDAY=1SU;BYMONTH=11\r\nEND:STANDARD\r\n"
        "BEGIN:DAYLIGHT\r\nDTSTART:16010101T020000\r\nTZOFFSETFROM:-0500\r\nTZOFFSETTO:-0400\r\n"
        "RRULE:FREQ=YEARLY;BYDAY=2SU;BYMONTH=3\r\nEND:DAYLIGHT\r\nEND:VTIMEZONE\r\n"
        "BEGIN:VEVENT\r\nUID:fiu-1\r\nSUMMARY:Gallery Talk\r\n"
        "DTSTART;TZID=\"Eastern Time (US & Canada)\":20261105T180000\r\n"
        "DTEND;TZID=Eastern Time (US \r\n & Canada):20261105T193000\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    events = run_adapter(ics, payload, cfg, "jmof")
    assert [(e["title"], e["start"], e["end"]) for e in events] == [
        ("Gallery Talk", "2026-11-05T18:00:00-05:00", "2026-11-05T19:30:00-05:00")
    ]


def test_eventbrite_error_message_is_readable():
    import pytest
    import requests

    from .helpers import context

    class Resp:
        status_code = 400
        text = ""

        def json(self):
            return {"error": "ARGUMENTS_ERROR", "error_description": "There are errors with your arguments: time_filter - INVALID"}

    class Session:
        def get(self, url, **kw):
            err = requests.HTTPError("400")
            err.response = Resp()
            raise err

    cfg = config()
    ctx = context(cfg)
    ctx.session = Session()
    ctx.secrets = {"EVENTBRITE_TOKEN": "x"}
    src = next(s for s in cfg.sources if s.key == "el-carajo")
    with pytest.raises(RuntimeError, match="400: There are errors with your arguments"):
        eventbrite.fetch(src, ctx)
