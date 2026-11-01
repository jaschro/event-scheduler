from collector.dedupe import dedupe

from .helpers import config


def ev(id, source, title, start, **kw):
    base = {
        "id": id, "title": title, "venue": source, "kind": "tech", "start": start, "end": None,
        "all_day": False, "description": "", "url": "https://x.test", "location": None,
        "price": {"free": None, "min": None, "text": None}, "source": source,
        "also_listed_by": [], "fetched_at": "t", "city": "miami",
    }
    base.update(kw)
    return base


def sources():
    return {s.key: s for s in config().sources}


def test_same_id_merges():
    out = dedupe([ev("a", "manatech", "X", "2026-11-04T18:00:00-05:00"),
                  ev("a", "manatech", "X", "2026-11-04T18:00:00-05:00")], sources())
    assert len(out) == 1


def test_venue_beats_aggregators_and_records_them():
    events = [
        ev("1", "refresh-miami", "Hack Night!", "2026-11-04T18:30:00-05:00", location="LAB"),
        ev("2", "hello-miami", "hack night", "2026-11-04T18:40:00-05:00"),
        ev("3", "miamibeach-arts", "Hack  Night", "2026-11-04T18:25:00-05:00"),
    ]
    out = dedupe(events, sources())
    assert len(out) == 1
    winner = out[0]
    assert winner["source"] == "hello-miami"
    assert winner["also_listed_by"] == ["miamibeach-arts", "refresh-miami"]
    assert winner["location"] == "LAB"  # gap filled from the aggregator


def test_aggregator_priority_order():
    events = [
        ev("1", "miamibeach-arts", "Jazz Night", "2026-11-04T20:00:00-05:00"),
        ev("2", "refresh-miami", "Jazz Night", "2026-11-04T20:00:00-05:00"),
    ]
    out = dedupe(events, sources())
    assert [e["source"] for e in out] == ["refresh-miami"]
    assert out[0]["also_listed_by"] == ["miamibeach-arts"]


def test_not_merged_outside_15_minutes_or_same_source():
    events = [
        ev("1", "hello-miami", "Meetup", "2026-11-04T18:00:00-05:00"),
        ev("2", "refresh-miami", "Meetup", "2026-11-04T18:21:00-05:00"),
        ev("3", "hello-miami", "Meetup", "2026-11-04T18:05:00-05:00"),
    ]
    out = dedupe(events, sources())
    # 21 and 16 minutes apart: no match; the two hello-miami sessions stay separate.
    assert len(out) == 3
    assert sum(1 for e in out if e["source"] == "hello-miami") == 2
