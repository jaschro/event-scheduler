// Page settings. Nothing in here is secret.
window.APP_CONFIG = {
  // Cities shown in the switch, in order. A city with no collected events still shows.
  cities: [
    { key: "miami", name: "Miami", tz: "America/New_York" },
    { key: "nyc", name: "New York", tz: "America/New_York" },
  ],
  defaultCity: "miami",

  // Where events.json / status.json live, tried in order.
  // "data/" on GitHub Pages; "../data/" when serving the repo root locally.
  dataBases: ["data/", "../data/"],

  daysAhead: 14,
  pxPerMinute: 1,          // 1 px per minute: one hour is 60 px
  minBlockPx: 20,          // shortest block, so short items stay clickable
  sideBySideMinutes: 30,   // overlapping items starting this close share the width
  nestIndent: 0.12,
  maxLanes: 3,             // at most this many side by side; the rest go in a "+N more" block
  maxDepth: 2,             // at most this many levels of nesting
  longEventHours: 10,      // timed items at least this long go in the all-day strip        // later items inside a longer one: indent as a share of column width
  noEndDisplayMinutes: 60, // block length on the page for events with no end time
  addDefaultMinutes: 120,  // length used by "+" when an event has no end (step 3)

  // Google sign-in (SPEC.md section 7). The client id is public by design; there is no secret.
  googleClientId: "751040903219-pci7ahiuq87h7agk3d726avsbam77ba0.apps.googleusercontent.com",
  googleLoginHint: "jasonchroman@gmail.com", // pre-selects this account in Google's window
  defaultCalendarColor: "#039be5",
  // false (spec default): the Google pass lives only in memory, so a reloaded tab reconnects
  // on your first click. true: also keep it in this tab's sessionStorage (cleared when the tab
  // closes, gone after about an hour), so reloads keep you signed in without a click.
  keepTokenInTab: false,
};
