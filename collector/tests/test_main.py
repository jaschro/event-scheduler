import json

from collector.main import run

from .helpers import FIXTURES, NOW, config


class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.encoding = "utf-8"

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """Serves fixtures by URL; anything else fails like a broken site."""

    def __init__(self, routes):
        self.routes = routes

    def get(self, url, **kwargs):
        for prefix, body in self.routes.items():
            if url.startswith(prefix):
                return FakeResponse(body)
        raise ConnectionError(f"unreachable: {url}")


def test_run_writes_files_keeps_failed_sources_and_skips_unchanged(tmp_path):
    cfg = config()
    hello = next(s for s in cfg.sources if s.key == "hello-miami")
    hello.url = "https://feeds.test/hello.ics"
    manatech = next(s for s in cfg.sources if s.key == "manatech")
    manatech.url = manatech.luma_calendar = None  # no feed configured at all
    ics = (FIXTURES / "luma_sample.ics").read_text(encoding="utf-8")
    eb = (FIXTURES / "eventbrite_sample.json").read_text(encoding="utf-8")
    eb_page = json.dumps(json.loads(eb)[0])
    routes = {"https://feeds.test/hello.ics": ics, "https://www.eventbriteapi.com/v3/organizers/40632499343/": eb_page}
    secrets = {"EVENTBRITE_TOKEN": "x"}

    rc = run(cfg, tmp_path, now_utc=NOW, session=FakeSession(routes), secrets=secrets)
    assert rc == 0
    events = json.loads((tmp_path / "events.json").read_text())
    status = json.loads((tmp_path / "status.json").read_text())
    assert events["cities"] == [{"key": "miami", "name": "Miami", "tz": "America/New_York"}]
    assert {e["source"] for e in events["events"]} == {"hello-miami", "el-carajo"}
    assert all(e["city"] == "miami" for e in events["events"])
    assert status["sources"]["hello-miami"]["result"] == "ok"
    assert status["sources"]["el-carajo"]["result"] == "ok"
    assert status["sources"]["manatech"]["result"] == "failed"
    assert "not configured" in status["sources"]["manatech"]["error"]
    assert status["sources"]["refresh-miami"]["result"] == "failed"
    assert status["sources"]["pamm"]["result"] == "skipped"
    n = len(events["events"])

    # Same data again: files are not rewritten.
    before = (tmp_path / "events.json").stat().st_mtime_ns, (tmp_path / "status.json").read_text()
    later = NOW.replace(minute=5)
    run(cfg, tmp_path, now_utc=later, session=FakeSession(routes), secrets=secrets)
    assert (tmp_path / "events.json").stat().st_mtime_ns == before[0]
    assert (tmp_path / "status.json").read_text() == before[1]

    # hello-miami breaks: its events are kept from the last good run, failure recorded.
    routes.pop("https://feeds.test/hello.ics")
    rc = run(cfg, tmp_path, now_utc=later, session=FakeSession(routes), secrets=secrets)
    assert rc == 0
    events2 = json.loads((tmp_path / "events.json").read_text())
    status2 = json.loads((tmp_path / "status.json").read_text())
    assert len(events2["events"]) == n
    s = status2["sources"]["hello-miami"]
    assert s["result"] == "failed" and s["event_count"] > 0 and s["last_success"] == NOW.isoformat(timespec="seconds")


def test_run_fails_only_when_every_source_fails(tmp_path):
    cfg = config()
    rc = run(cfg, tmp_path, now_utc=NOW, session=FakeSession({}), secrets={})
    assert rc == 1
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["summary"]["ok"] == 0
