# Event Scheduler: Build Spec

Draft as of Nov 1, 2026. Written to hand to Claude Code as the brief for the build.

## 1. Goal and scope

A personal web page, hosted on GitHub Pages at jaschro.github.io/event-scheduler (public repo jaschro/event-scheduler), that shows upcoming events from about 29 Miami and Miami Beach venues, one day at a time, with Jason's own Google Calendar beside them. Events sit on the left, his calendar on the right, lined up by time. A "+" after each event adds it to his calendar, and it shows up on the right straight away. It is built for several cities from the start: Miami now, New York later, with a city switch at the top of the page.

In scope: a collector that runs twice a week, a normalized events file, the static page, Google sign-in for the calendar side, and the add button.

Out of scope for v1: ticket buying, notifications, other people's calendars, a backend server or database.

## 2. Architecture

- **Collector**: a Python 3.12 script run by a GitHub Action on a cron (Monday and Thursday at 6:00 AM Eastern; GitHub's cron runs in UTC, so 11:00 UTC gives 6 AM in winter and 7 AM in summer), plus a manual "Run workflow" button. It reads `sources.yaml`, pulls each source, normalizes events, and writes `data/events.json` and `data/status.json`.
- **Publish**: the same workflow commits the data only when it changed, then deploys the site with GitHub's Pages actions. The workflow's built-in `GITHUB_TOKEN` (with `contents: write`, `pages: write`, `id-token: write`) covers both, so no Personal Access Token is needed. A fine-grained PAT, scoped to this one repo with Contents read/write, is only a fallback if something outside the Action ever has to push.
- **Page**: plain HTML, CSS and JavaScript, no build step. It loads `events.json` from the same site. The calendar side runs entirely in his browser after he signs in with Google; nothing about his calendar is stored in the repo or on any server.

Suggested repo layout:

```
sources.yaml            # one entry per venue (see section 3)
collector/
  main.py               # runs all sources, merges, writes data/
  adapters/ics.py       # iCal feeds
  adapters/eventbrite.py
  adapters/tribe.py     # WordPress "The Events Calendar" REST API
  adapters/jsonld.py    # schema.org Event data embedded in pages
  adapters/custom/      # one small file per hand-written page reader
  normalize.py, dedupe.py
  tests/                # saved sample pages + expected output per adapter
data/events.json
data/status.json
site/index.html, app.js, styles.css, config.js
.github/workflows/collect.yml
```

**Cities.** `sources.yaml` opens with a `cities` block: key, display name and time zone for each city (`miami` now, `nyc` later; both America/New\_York). Every venue entry carries a `city` key. One collector run loops over all cities and writes a single `events.json` in which every event names its city. Adding a city means adding its block and its venues; no code changes.

## 3. How each Miami venue is collected

The collector tries the cheapest reliable method first. Order for any new source: iCal feed, then an official API, then the WordPress events REST API if the site runs The Events Calendar plugin, then schema.org Event JSON-LD on the page, then a hand-written page reader, and a headless browser (Playwright) only for pages that build their listings with script.

Luma feed URLs should be copied from each calendar page's "Add iCal Subscription" button rather than built by hand. Eventbrite organizer pages use the organizer id already in Jason's links.

| Venue | Kind | Method | Source | Notes |
| --- | --- | --- | --- | --- |
| City of Miami Beach arts calendar | aggregator | iCal | events.miamibeachfl.gov/arts-and-culture/ | Has an iCal subscribe option; aggregator, lowest priority in dedupe |
| Refresh Miami | tech, aggregator | iCal | refreshmiami.com/events/ | iCal subscribe; overlaps ManaTech and others |
| Luma Miami | mixed, aggregator | iCal if offered, else page data | luma.com/miami | City discovery page, may not have a feed; high volume, filter hard |
| ManaTech | tech | Luma iCal | luma.com/manatech |  |
| Hello Miami | tech | Luma iCal | luma.com/hello\_miami | Weekly hack nights |
| Miami AI Hub | tech | Luma iCal | luma.com/miamiaihub | Monthly |
| Venture Café Miami | tech | page reader | venturecafemiami.org | Weekly Thursday Gathering; can be generated as a recurring event if the page has no dates |
| El Carajo | food and wine | Eventbrite API | eventbrite.com/o/40632499343 | Paid dinners; keep price |
| 840 Miami | wellness | Eventbrite API | eventbrite.com/o/16691144833 | New and full moon beach yoga |
| Healthyme.Love | wellness | Eventbrite API | eventbrite.com/o/27397413755 | Full moon ceremonies |
| UM Rosenstiel (Johnson Center) | science, talks | Eventbrite API | eventbrite.com/o/121856689354 | Key Biscayne |
| Jewish Museum of Florida-FIU | museum | likely calendar platform feed | calendar.fiu.edu/jmof | FIU's calendar likely offers iCal or JSON; verify. Nothing listed until Jan 2027 |
| The Bass | museum | page reader | thebass.org/events/ | Third Thursdays monthly |
| PAMM | museum | page reader | pamm.org/events |  |
| Wolfsonian-FIU | museum | page reader | wolfsonian.org/whats-on/events/index.html |  |
| ICA Miami | museum | page reader | icamiami.org/calendar/ |  |
| Rubell Museum | museum | page reader | rubellmuseum.org/support/member-events | Page stale since Aug; mixes member-only items; low priority |
| Frost Science | museum | page reader | frostscience.org/calendar-events/ |  |
| Oolite Arts | art | page reader | oolitearts.org/calendar/ |  |
| O Cinema South Beach | film | headless browser | o-cinema.org/o-cinema-south-beach | Ticketing widget loads by script |
| Coral Gables Art Cinema | film | headless browser | gablescinema.com/calendar/ | Same kind of ticketing widget |
| Arsht Center | stage, music | page reader | arshtcenter.org/calendar/ | Large volume |
| Miami New Drama (Colony) | stage | page reader | miaminewdrama.org/shows-events/ | Show runs; expand to each performance date |
| Miami Beach Bandshell | music | page reader | miamibeachbandshell.com/events/ |  |
| New World Center / NWS | music | headless browser | nws.edu/tickets/concerts-and-events/ | Dates load by script |
| Books & Books | books, talks | page reader | shop.booksandbooks.com/events |  |
| Miami Beach JCC | community | page reader | mbjcc.org/events |  |
| Miami Beach Botanical Garden | outdoors | page reader | mbgarden.org/calendar |  |

**New York, later.** Its venues get added as more entries with city `nyc`, using the same methods. Jason already has a Claude project that searches New York events and emails him twice a week; its venue list could seed this one when the time comes. Nothing from it is copied into this spec.

For every "page reader" source, Claude Code should first check whether the site runs The Events Calendar plugin or embeds JSON-LD, since either avoids a custom reader. Expect page readers to break now and then when a site changes; the status file makes that visible.

## 4. Event schema

Each item in `events.json`:

| Field | Type | Notes |
| --- | --- | --- |
| id | string | Stable hash of source + the source's own event id, or of source + normalized title + start when there is no id |
| title | string | Plain text |
| venue | string | Display name from `sources.yaml` |
| kind | string | tech, museum, art, film, stage, music, talks, science, food and wine, wellness, community, outdoors |
| start | string | ISO 8601 with offset, in America/New\_York |
| end | string or null | Same format |
| all\_day | boolean |  |
| description | string | Plain text, HTML stripped, trimmed to about 600 characters |
| url | string | Event page, http or https only |
| location | string or null | Address or room if given |
| price | object | `{free: bool or null, min: number or null, text: string or null}` |
| source | string | Key from `sources.yaml` |
| also\_listed\_by | list | Other sources that carried the same event |
| fetched\_at | string | ISO timestamp |
| city | string | Key from the cities block, such as miami or nyc |

`status.json` holds, per source: last run result (ok or failed), event count, error message, and last successful run.

## 5. Collector behavior

- **Window**: today through 14 days ahead. Drop anything that has ended.
- **Time zones**: convert everything to the city's time zone from the config (America/New\_York for both Miami and New York). Times with no zone get the city's zone. Handle all-day and multi-day events; a show run is expanded into one event per performance when dates are given. Weekly repeats (Venture Café Thursdays, Hello Miami hack nights) appear every week: recurring events are expanded into one event per occurrence inside the 14-day window.
- **Dedupe**: same id merges. Across sources, events with the same normalized title and a start within 15 minutes are one event; keep the venue's own listing and record aggregators in `also_listed_by`.
- **Failures**: each source runs on its own with a timeout. A failed source keeps its events from the last good run (so a venue doesn't vanish), and the failure is logged in `status.json`. The run only fails outright if every source fails.
- **Manners**: a clear user agent, about one request per second per site, respect robots rules, no logins.
- **Tests**: each adapter has a saved sample and expected output, run in the workflow before collecting.
- **Commit**: only when `events.json` or `status.json` changed.

## 6. Page layout and behavior

**City switch.** A toggle at the top of the page (Miami, New York) picks which city's events fill the left column. It opens on the last city chosen, remembered in the browser, and starts on Miami. His calendar column doesn't change with it. With only one city loaded, the toggle still shows so New York slots in later.

**Day bands.** The page is a vertical list of days, starting today. Each day is a band with the date as its heading and three parts side by side: an hour-label gutter, the venue events column and his calendar column. Both columns share one vertical scale (about 1 px per minute, so an hour is 60 px), so a given time sits at the same height on both sides. Each band shows only the hours from that day's first item to its last across both columns, rounded out to whole hours, not all 24. A day with nothing on either side is skipped.

**All-day strip.** All-day and multi-day items sit in a strip at the top of the band, above the grid, on their own side.

**Time grid.** Every timed item is a block whose top is its start time and whose height is its length, with a minimum of about 20 px so short items stay clickable. Hour lines run across both columns.

**Overlaps, Google style.** Items that overlap form a cluster. Within a cluster, items that start within 30 minutes of each other split the column width side by side, one lane each. An item that starts later inside a longer one is indented to the right and drawn on top with a thin light border, so both stay readable, as in Google Calendar's day view. The same layout code serves both columns, so three meetups at 6:30 PM sit side by side on the left just as overlapping meetings do on the right.

**Venue event blocks.** Compact: start time and title, with the venue on a second line when the block is tall enough; text truncates to fit. Blocks are tinted by kind in a muted palette. Clicking a block opens a popover with the full time range, venue, price or Free, the description, a link to the event page and the "+".

**The "+" button.** Inserts an event into the primary calendar of jasonchroman@gmail.com with the title, venue as location, description plus the event link, and start and end (2 hours by default when no end is given), with no reminder: reminders set to useDefault false and no overrides. It tags the new calendar event with the venue event's id in a private property. On success the event appears in the right column without a reload and the "+" turns into a check. On load, the page looks for that tag on his events, so anything already added shows the check and can't be added twice.

**His calendar blocks.** Before sign-in, the right column shows a "Sign in with Google to see your calendar" prompt and the "+" buttons are disabled. After sign-in, his events render as rounded blocks in each event's own Google color, showing title, time range and location, truncated to fit. The page keeps a built-in copy of Google's 11 event colors and maps each event's colorId to it; events with no colorId use one default color set in `config.js` (reading the calendar's own color would need an extra scope). Events he declined are drawn lighter, outline only, as Google does. Clicking one opens a small read-only popover with title, time and location. Venue blocks that overlap one of his events get a subtle conflict mark (nice to have).

**Filters (nice to have).** Kind, venue, free only, and a text search, remembered in the browser. A "jump to date" control.

**Footer.** "Last updated" from the data file, and a short list of sources that failed on the last run.

**Phone (nice to have).** The two columns switch with tabs (Events, My calendar) over the same time grid, or stack, whichever reads better.

**Safety.** All scraped text is inserted as text, never as HTML, and only http and https links are rendered, so a venue page can't inject script into his page.

## 7. Google sign-in and Calendar

**In plain terms.** The calendar connection is not a PAT. A PAT only lets a program push to GitHub, and the Action's built-in token already covers that. The calendar link is a Google sign-in that happens in Jason's own browser tab:

- He presses "Sign in with Google" and Google's own window asks him to allow access to his calendar events.
- Only jasonchroman@gmail.com can get through, because the Google app stays in Testing mode with that account as its only test user. Google turns anyone else away.
- Google gives the page a short-lived pass (an access token) good for about an hour. It is kept only in that tab's memory: never saved, never sent to GitHub, never in the repo. Closing the tab ends it.
- The page uses the pass to read his events for the 14 days shown and to add an event when he presses "+". It can't reach any other Google data.
- The only Google value in the repo is the client id, which is public by design. It names the page to Google and grants nothing by itself.
- Any other visitor sees just the public venue events, with no calendar column and no working "+".
- He signs in again on each visit or after about an hour; while in Testing, Google may also ask him to re-approve about once a week.

**Technical details**

- Use Google Identity Services' token client in the browser, with the Calendar API called directly from the page.
- Scope: `https://www.googleapis.com/auth/calendar.events` only. It covers reading and adding events on his primary calendar (calendar id `primary`), so no calendar-list scope is needed.
- The access token lives in memory only and lasts about an hour; the page asks again quietly when it expires. In testing mode, Google may ask him to approve again about once a week.
- The OAuth client id goes in `site/config.js`. It is not a secret. No API key or client secret is used.

**One-time setup for Jason** (about 15 minutes, done by him in Google Cloud Console):

1. Create a Google Cloud project (any name, such as "Event Scheduler").
2. Enable the Google Calendar API.
3. Set up the OAuth consent screen as External, leave it in Testing, add the calendar.events scope, and add jasonchroman@gmail.com as the only test user.
4. Create an OAuth client id of type Web application. Add authorized JavaScript origins for the Pages site (https://jaschro.github.io; an origin has no path, so this covers /event-scheduler) and http://localhost:8000 for local testing.
5. Copy the client id into `site/config.js`.

## 8. Security notes

- No secrets in the repo. The only secret is the Eventbrite private token, stored as a repository Actions secret named `EVENTBRITE_TOKEN`.
- Workflow permissions set to the minimum listed in section 2; third-party actions pinned to fixed versions.
- The page is public, but his calendar only appears in his own browser after he signs in. Nobody else can see or change it, since the OAuth app is in testing mode with only him as a user.
- Calendar scope limited to events; the page never deletes or edits his existing events.

## 9. Build order and done criteria

1. Collector with the feed sources (Luma calendars, Eventbrite, Miami Beach and Refresh Miami), schema, dedupe, status file, and the workflow on cron.
2. Page with day bands and event cards, no calendar yet.
3. Google sign-in, his calendar on the right, the shared time grid with Google-style overlaps, and the "+" with duplicate prevention.
4. Page readers for the remaining venues, heaviest first (Arsht, PAMM, Bass, Frost), then the script-built pages.
5. Filters, conflict marks, phone layout.

Done when: the workflow runs on schedule and on demand; `events.json` holds events from at least 25 of the 29 sources; a broken source shows in the footer without breaking the page; after sign-in his events show beside the venue events for each day; "+" adds an event that appears at once and can't be added twice; all times are in the city's time zone; the city switch works with Miami as the only city.

## 10. Decisions (Nov 1)

| Question | Decision |
| --- | --- |
| Calendar to read and add to | Primary calendar of jasonchroman@gmail.com |
| Days ahead | 14 |
| Repo | Public: jaschro/event-scheduler, page at jaschro.github.io/event-scheduler |
| Run schedule | Monday and Thursday mornings, Eastern |
| Weekly repeats | Show every week |
| Reminders on added events | None |
| PAT | Not needed; calendar access is the Google sign-in in section 7 |
| Cities | Miami now, New York later, with a city switch on the page |

Nothing is left open. The spec is ready to hand to Claude Code.
