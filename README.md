# Event Scheduler

A list of events on one side and a calendar on the other: upcoming events from Miami
venues, day by day, next to your own Google Calendar.
See [SPEC.md](SPEC.md) for the full brief.

## Status

Build steps 1-3 of 5 (SPEC.md section 9): the collector, feed sources, schema, dedupe,
status file and scheduled workflow; the page (day bands, time grid, event blocks,
popovers, city switch, footer); and Google sign-in with your calendar on the right and
the "+" that adds an event (with duplicate prevention).

## Layout

```
sources.yaml              cities + one entry per venue
collector/main.py         runs all sources, merges, writes data/
collector/adapters/       ics.py, eventbrite.py (tribe, jsonld, custom readers come later)
collector/normalize.py    event schema, HTML stripping, time zones, ids
collector/dedupe.py       same-id and cross-source merging
collector/polite.py       user agent, 1 request/second per host, robots.txt
collector/tests/          saved samples + expected output per adapter
data/events.json          output (committed by the workflow)
data/status.json          per-source result, count, error, last success
site/                     the page: index.html, app.js, styles.css, config.js
.github/workflows/collect.yml
```

## Run locally

```bash
pip install -r requirements.txt
```

```bash
python -m pytest -q collector/tests
```

```bash
EVENTBRITE_TOKEN=... python -m collector.main          # all sources
```

```bash
python -m collector.main --only manatech hello-miami   # just some
```

View the page locally (serves the repo root so the page finds ../data/):

```bash
python -m http.server 8000
```

then open http://localhost:8000/site/

Regenerate an adapter's expected output after an intended change:
`UPDATE_EXPECTED=1 python -m pytest collector/tests`, then review the diff.

## Behaviour notes

- Window: today 00:00 through 14 days ahead (city time zone); ended events dropped.
- Recurring iCal events are expanded per occurrence; overrides and exclusions honoured.
- A failed source keeps its last good events; the failure is recorded in `status.json`.
  The collector exits non-zero only if every attempted source failed; the workflow still
  publishes the page (failures show in its footer) and then marks the run as failed.
- Data files are rewritten only when something other than timestamps changed, so the
  workflow commits only real changes.
- Sources marked `enabled: false` are later build steps and show as `skipped`.

## Setup still needed (owner only)

1. Luma feed URLs for ManaTech, Hello Miami and Miami AI Hub (and Luma Miami if it has one):
   on each calendar page, "Add iCal Subscription", copy the link into `sources.yaml`.
2. Miami Beach arts calendar: copy its iCal subscribe link into `sources.yaml`.
3. Refresh Miami: confirm `https://refreshmiami.com/events/?ical=1` returns a feed.
4. Eventbrite private token as the repository Actions secret `EVENTBRITE_TOKEN`.
5. Settings → Pages → Source: "GitHub Actions" (needed from step 2, when there is a site).

Done: Google Cloud project with the Calendar API, consent screen in Testing with
jasonchroman@gmail.com as the only test user, `calendar.events` scope, and a web OAuth
client (origins `https://jaschro.github.io`, `http://localhost:8000`) whose public client
id is in `site/config.js`.
