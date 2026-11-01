# Event Scheduler

A list of events on one side and a calendar on the other: upcoming events from Miami
venues, day by day, next to your own Google Calendar.
See [SPEC.md](SPEC.md) for the full brief.

## Status

Build steps 1-4 of 5 plus step 5's filters (SPEC.md section 9): the collector, feed sources, schema, dedupe,
status file and scheduled workflow; the page (day bands, time grid, event blocks,
popovers, city switch, footer); and Google sign-in with your calendar on the right and
the "+" that adds an event (with duplicate prevention); and page readers for the
venues without a feed, Ticketmaster for both cities, and the New York sources.

## Layout

```
sources.yaml              cities + one entry per venue
collector/main.py         runs all sources, merges, writes data/
collector/adapters/       ics, eventbrite, tribe (The Events Calendar API), jsonld (schema.org),
                          ticketmaster, custom/ (one reader per venue; whenparse.py reads date text)
collector/probe.py        finds the cheapest working method for a source (runs on probe/** branches)
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

1. New Luma calendars: on the calendar page, "Add iCal Subscription", copy the link
   into `sources.yaml` as `url`. (Or set `luma_calendar: <page name>` to have the
   collector look the feed up itself, using Luma's unofficial page lookup.)

Done: feed links for Miami Beach arts, Refresh Miami, The Bass and the four Luma calendars;
`TICKETMASTER_API_KEY` secret; the
`EVENTBRITE_TOKEN` Actions secret; Pages source set to GitHub Actions.

Done: Google Cloud project with the Calendar API, consent screen in Testing with
jasonchroman@gmail.com as the only test user, `calendar.events` scope, and a web OAuth
client (origins `https://jaschro.github.io`, `http://localhost:8000`) whose public client
id is in `site/config.js`.

## How each Miami venue without a feed is collected (probed Nov 1, 2026)

None of these sites runs The Events Calendar REST API. In order of preference:

| Venue | Method |
| --- | --- |
| Coral Gables Art Cinema | schema.org JSON-LD on its Agile Ticketing "full calendar" page |
| ICA Miami | listing page + schema.org JSON-LD on each event page (custom `ica`) |
| Oolite Arts | custom HTML reader (`oolite`); weekly workshops expanded per session |
| O Cinema South Beach | custom HTML reader (`ocinema`); showtimes are in the server HTML, no browser needed |
| Miami New Drama | Spektrix ticketing API, one entry per performance (`spektrix`) |
| New World Symphony | Playwright for the script-built listing, times from each concert page (`nws`) |
| Miami Beach JCC | event pages found via the site's sitemap (`mbjcc`) |
| Miami Beach Botanical Garden | Squarespace collection JSON (`squarespace`) |
| Rubell Museum | custom HTML reader (`rubell`); page stale since August |
| Arsht Center | via the Greater Miami tourism site's Arsht page (`simpleview`); dates only, times borrowed from Ticketmaster when the same show is listed there |

Films with no end time are assumed to run 2.5 hours (`default_minutes_by_kind`).

### Blocked sources

- **PAMM**: its pages answer 403 to automated readers; its WordPress API lists events without dates.
- **Wolfsonian-FIU**: the site does not accept connections from GitHub's runners.
- **Arsht Center (own site)**: bot protection blocks its events API (hence the tourism-site route).
- **NYC**: CCNY Spitzer answers 403; CFA Society NY's robots.txt disallows its iCal export.

## Ticketmaster

`ticketmaster-miami` and `ticketmaster-nyc` use the Discovery API with the
`TICKETMASTER_API_KEY` secret, one query per day over the window. Each event keeps
its own venue and a kind from Ticketmaster's classification. They are aggregators,
so a venue's own listing wins in dedupe. Timed-entry attractions (a ticket every
15–30 minutes) are collapsed to one item per day. Errors written to `status.json`
are scrubbed of the key.

## Page filters (venue events only; your calendar always shows everything)

Remembered per city in your browser: kind chips, "Hide this venue" / "Hide this title"
from an event's popup (undo under "Hidden"), text search, jump to date, and "One card
per show per day" (on by default), which turns repeated showtimes of the same film or
show at one venue into one card listing its times.
