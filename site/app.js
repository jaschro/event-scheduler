/* Event Scheduler page. Plain JS, no build step.
 *
 * Safety: every piece of scraped text goes in with textContent, never innerHTML,
 * and only http/https links are rendered (SPEC.md section 6, Safety).
 *
 * Google: the access token lives only in this tab's memory (SPEC.md section 7).
 */
(function () {
  "use strict";

  const CFG = window.APP_CONFIG;
  const STORE_CITY = "es.city";
  const STORE_GCAL = "es.gcal";      // "you were signed in before" flag (no token), localStorage
  const SESSION_TOKEN = "es.gtoken"; // only when CFG.keepTokenInTab: token + expiry, sessionStorage
  const DAY_MIN = 24 * 60;
  const SCOPE = "https://www.googleapis.com/auth/calendar.events";
  const CAL_API = "https://www.googleapis.com/calendar/v3/calendars/primary/events";
  const PRIVATE_KEY = "eventSchedulerId"; // private extended property on events we add

  // Google Calendar's 11 event colours, by colorId.
  const GOOGLE_COLORS = {
    1: "#7986cb", 2: "#33b679", 3: "#8e24aa", 4: "#e67c73", 5: "#f6bf26", 6: "#f4511e",
    7: "#039be5", 8: "#616161", 9: "#3f51b5", 10: "#0b8043", 11: "#d50000",
  };

  // ---------- small helpers ----------

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function safeHref(url) {
    return typeof url === "string" && /^https?:\/\/[^\s]+$/i.test(url) ? url : null;
  }

  function storeGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }

  function storeSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* private mode etc. */ }
  }

  function storeRemove(key) {
    try { window.localStorage.removeItem(key); } catch (e) { /* ignore */ }
  }

  function sessionGet(key) {
    try { return window.sessionStorage.getItem(key); } catch (e) { return null; }
  }

  function sessionSet(key, value) {
    try {
      if (value == null) window.sessionStorage.removeItem(key);
      else window.sessionStorage.setItem(key, value);
    } catch (e) { /* ignore */ }
  }

  // Times are wall-clock ISO strings in the city's zone ("2026-11-04T18:30:00-05:00" or
  // without offset), so the date and minutes can be read straight off the string.
  function wall(iso) {
    return { date: iso.slice(0, 10), min: Number(iso.slice(11, 13)) * 60 + Number(iso.slice(14, 16)) };
  }

  // A moment -> wall-clock "YYYY-MM-DDTHH:MM:SS" in a zone.
  function wallIso(ms, tz) {
    return new Intl.DateTimeFormat("sv-SE", {
      timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
    }).format(new Date(ms)).replace(" ", "T");
  }

  function addDays(dateStr, n) {
    const d = new Date(dateStr + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }

  function daysBetween(a, b) {
    return Math.round((Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / 86400000);
  }

  function todayIn(tz) {
    return wallIso(Date.now(), tz).slice(0, 10);
  }

  function fmtMin(min) {
    const m = ((min % DAY_MIN) + DAY_MIN) % DAY_MIN;
    const h = Math.floor(m / 60);
    const mm = m % 60;
    const h12 = h % 12 === 0 ? 12 : h % 12;
    return `${h12}${mm ? ":" + String(mm).padStart(2, "0") : ""} ${h < 12 ? "AM" : "PM"}`;
  }

  function fmtHour(h) {
    if (h === 0 || h === 24) return "12 AM";
    if (h === 12) return "Noon";
    return `${h % 12} ${h < 12 ? "AM" : "PM"}`;
  }

  function fmtDate(dateStr, opts) {
    return new Intl.DateTimeFormat("en-US", { timeZone: "UTC", ...opts }).format(new Date(dateStr + "T12:00:00Z"));
  }

  function dayHeading(dateStr, today) {
    const diff = daysBetween(today, dateStr);
    const label = fmtDate(dateStr, { weekday: "long", month: "long", day: "numeric" });
    if (diff === 0) return ["Today", label];
    if (diff === 1) return ["Tomorrow", label];
    return [null, label];
  }

  function kindClass(kind) {
    return "kind-" + String(kind || "other").toLowerCase().replace(/[^a-z]+/g, "-");
  }

  function timeRange(ev) {
    const s = wall(ev.start);
    const short = { weekday: "short", month: "short", day: "numeric" };
    if (ev.all_day) {
      const lastDay = ev.end ? addDays(wall(ev.end).date, -1) : s.date;
      if (lastDay <= s.date) return fmtDate(s.date, short) + " · all day";
      return fmtDate(s.date, { month: "short", day: "numeric" }) + " – " + fmtDate(lastDay, { month: "short", day: "numeric" });
    }
    const day = fmtDate(s.date, short);
    if (!ev.end) return `${day} · ${fmtMin(s.min)}`;
    const e = wall(ev.end);
    if (e.date === s.date) return `${day} · ${fmtMin(s.min)} – ${fmtMin(e.min)}`;
    return `${day} ${fmtMin(s.min)} – ${fmtDate(e.date, short)} ${fmtMin(e.min)}`;
  }

  function priceText(price) {
    if (!price) return null;
    if (price.text) return price.text;
    if (price.free === true) return "Free";
    if (price.min != null) return price.min === 0 ? "Free" : `From $${price.min}`;
    return null;
  }

  // ---------- turning items into per-day pieces ----------
  //
  // An item is {start, end, all_day, startMs?, endMs?}: venue events as they come in
  // events.json, calendar events after toCalItem(). Returns Map(date -> {allDay, timed}),
  // each timed piece {ev, s, e} in minutes of that day.
  function piecesByDay(items, firstDay, lastDay, nowMs, hideEnded) {
    const days = new Map();
    const slot = (d) => {
      if (!days.has(d)) days.set(d, { allDay: [], timed: [] });
      return days.get(d);
    };
    const inRange = (d) => d >= firstDay && d <= lastDay;

    for (const ev of items) {
      const s = wall(ev.start);
      const startMs = ev.startMs != null ? ev.startMs : Date.parse(ev.start);
      const endMs = ev.endMs != null ? ev.endMs : ev.end ? Date.parse(ev.end)
        : startMs + (ev.all_day ? DAY_MIN : CFG.noEndDisplayMinutes) * 60000;
      // Hide venue events that have ended (the data file can be a few days old).
      if (hideEnded && endMs <= nowMs) continue;

      const e = ev.end ? wall(ev.end) : null;
      const longTimed = !ev.all_day && ev.end && endMs - startMs >= DAY_MIN * 60000;

      if (ev.all_day || longTimed) {
        // All-day and multi-day items go in the strip of every day they cover.
        let last = e ? e.date : s.date;
        if (e && e.min === 0 && last > s.date) last = addDays(e.date, -1);
        for (let d = s.date; d <= last; d = addDays(d, 1)) {
          if (inRange(d)) slot(d).allDay.push({ ev });
        }
        continue;
      }

      const endDate = e ? e.date : s.date;
      const endMin = e ? e.min : Math.min(DAY_MIN, s.min + CFG.noEndDisplayMinutes);
      if (endDate === s.date || (e && e.min === 0 && daysBetween(s.date, endDate) === 1)) {
        // Same day (an end at exactly midnight counts as the same day).
        const em = endDate === s.date ? endMin : DAY_MIN;
        if (inRange(s.date)) slot(s.date).timed.push({ ev, s: s.min, e: Math.max(em, s.min) });
      } else {
        // Crosses midnight: one piece per day.
        if (inRange(s.date)) slot(s.date).timed.push({ ev, s: s.min, e: DAY_MIN });
        if (inRange(endDate) && endMin > 0) slot(endDate).timed.push({ ev, s: 0, e: endMin, contStart: true });
      }
    }
    return days;
  }

  // ---------- Google-style overlap layout (shared by both columns) ----------
  //
  // Items that start within `sideBySideMinutes` of each other and overlap form a row and
  // split the width side by side. An item that starts later inside a longer one starts a
  // new row, indented from the item it sits in and drawn on top with a thin border.
  // Returns each item with {left, width, z, nested} (left/width as fractions of the column).
  function layoutColumn(items) {
    const minMinutes = CFG.minBlockPx / CFG.pxPerMinute;
    const sorted = items
      .map((it) => ({ ...it, ve: Math.max(it.e, it.s + minMinutes) }))
      .sort((a, b) => a.s - b.s || (b.e - b.s) - (a.e - a.s));

    const rows = [];
    for (const it of sorted) {
      let row = null;
      for (let i = rows.length - 1; i >= 0; i--) {
        const r = rows[i];
        if (it.s - r.start >= CFG.sideBySideMinutes) break;
        if (r.items.some((o) => o.ve > it.s)) { row = r; break; }
      }
      if (row) row.items.push(it);
      else rows.push({ start: it.s, items: [it] });
    }

    const placed = [];
    rows.forEach((row, idx) => {
      // The deepest already-placed item still running when this row starts is its parent.
      let parent = null;
      for (const p of placed) {
        if (p.s < row.start && p.ve > row.start && (!parent || p.left > parent.left || (p.left === parent.left && p.z > parent.z))) {
          parent = p;
        }
      }
      const base = parent ? Math.min(parent.left + CFG.nestIndent, 0.75) : 0;
      const width = (1 - base) / row.items.length;
      row.items.forEach((it, i) => {
        it.left = base + i * width;
        it.width = width;
        it.z = idx + 1;
        it.nested = !!parent;
        placed.push(it);
      });
    });
    return placed;
  }

  // ---------- state ----------

  const state = {
    city: null,
    events: null,
    status: null,
    loadError: null,
    google: {
      token: null,       // access token, memory only
      expiresAt: 0,
      busy: false,
      error: null,
      cal: null,         // [calendar items] once loaded
      added: new Set(),  // venue event ids already on the calendar
    },
  };

  function knownCities() {
    const list = CFG.cities.slice();
    const fromData = (state.events && state.events.cities) || [];
    for (const c of fromData) {
      if (!list.some((x) => x.key === c.key)) list.push({ key: c.key, name: c.name, tz: c.tz });
    }
    return list;
  }

  function currentCity() {
    const list = knownCities();
    return list.find((c) => c.key === state.city) || list[0];
  }

  function signedIn() {
    return !!state.google.token && Date.now() < state.google.expiresAt;
  }

  // ---------- Google sign-in and Calendar ----------

  let tokenClient = null;

  function gisReady() {
    return new Promise((resolve, reject) => {
      const start = Date.now();
      (function wait() {
        if (window.google && google.accounts && google.accounts.oauth2) return resolve();
        if (Date.now() - start > 10000) return reject(new Error("Google sign-in didn't load. Check your connection or ad blocker."));
        setTimeout(wait, 100);
      })();
    });
  }

  // Ask Google for a token. Must run from a click (Google opens its own window).
  // prompt "" = no consent screen if already granted; "consent" = ask again.
  async function requestToken(prompt) {
    await gisReady();
    if (!tokenClient) {
      tokenClient = google.accounts.oauth2.initTokenClient({
        client_id: CFG.googleClientId,
        scope: SCOPE,
        login_hint: CFG.googleLoginHint || undefined,
        callback: () => {},
      });
    }
    return new Promise((resolve, reject) => {
      tokenClient.callback = (resp) => {
        if (resp.error) return reject(new Error(resp.error_description || resp.error));
        if (!google.accounts.oauth2.hasGrantedAllScopes(resp, SCOPE)) {
          return reject(new Error("Calendar access wasn't allowed. Sign in again and tick the calendar box."));
        }
        state.google.token = resp.access_token;
        // Treat it as expiring a minute early.
        state.google.expiresAt = Date.now() + (Number(resp.expires_in || 3600) - 60) * 1000;
        storeSet(STORE_GCAL, "1");
        if (CFG.keepTokenInTab) {
          sessionSet(SESSION_TOKEN, JSON.stringify({ t: state.google.token, e: state.google.expiresAt }));
        }
        resolve();
      };
      tokenClient.error_callback = (err) => reject(new Error(err && err.type === "popup_closed" ? "Sign-in window was closed." : (err && err.message) || "Sign-in failed."));
      tokenClient.requestAccessToken({ prompt });
    });
  }

  // Make sure a valid token exists; quietly re-asks when it has expired (call from a click).
  async function ensureToken() {
    if (signedIn()) return;
    await requestToken("");
  }

  async function gapi(url, options) {
    const resp = await fetch(url, {
      ...options,
      headers: { Authorization: `Bearer ${state.google.token}`, "Content-Type": "application/json", ...(options && options.headers) },
    });
    if (resp.status === 401) {
      state.google.token = null;
      state.google.expiresAt = 0;
      sessionSet(SESSION_TOKEN, null);
      throw new Error("Google sign-in expired. Sign in again.");
    }
    if (!resp.ok) {
      let msg = `Google Calendar error ${resp.status}`;
      try { msg = (await resp.json()).error.message || msg; } catch (e) { /* keep default */ }
      throw new Error(msg);
    }
    return resp.status === 204 ? null : resp.json();
  }

  function toCalItem(g, tz) {
    const allDay = !!(g.start && g.start.date);
    let start, end, startMs, endMs;
    if (allDay) {
      start = g.start.date + "T00:00:00";
      end = (g.end && g.end.date ? g.end.date : addDays(g.start.date, 1)) + "T00:00:00";
    } else {
      startMs = Date.parse(g.start.dateTime);
      endMs = g.end && g.end.dateTime ? Date.parse(g.end.dateTime) : startMs + 3600000;
      start = wallIso(startMs, tz);
      end = wallIso(endMs, tz);
    }
    const me = (g.attendees || []).find((a) => a.self);
    return {
      gcal: true,
      id: g.id,
      title: g.summary || "(No title)",
      start, end, startMs, endMs,
      all_day: allDay,
      location: g.location || null,
      color: GOOGLE_COLORS[g.colorId] || CFG.defaultCalendarColor,
      declined: !!(me && me.responseStatus === "declined"),
      link: g.htmlLink || null,
      scheduledId: ((g.extendedProperties || {}).private || {})[PRIVATE_KEY] || null,
    };
  }

  async function loadCalendar() {
    const tz = currentCity().tz;
    const now = Date.now();
    const params = new URLSearchParams({
      timeMin: new Date(now - 2 * 86400000).toISOString(),
      timeMax: new Date(now + ((CFG.daysAhead || 14) + 1) * 86400000).toISOString(),
      singleEvents: "true",
      orderBy: "startTime",
      maxResults: "2500",
      timeZone: tz,
    });
    const items = [];
    let pageToken = null;
    for (let i = 0; i < 10; i++) {
      if (pageToken) params.set("pageToken", pageToken);
      const data = await gapi(`${CAL_API}?${params}`);
      items.push(...(data.items || []));
      pageToken = data.nextPageToken;
      if (!pageToken) break;
    }
    state.google.cal = items.filter((g) => g.status !== "cancelled").map((g) => toCalItem(g, tz));
    state.google.added = new Set(state.google.cal.map((c) => c.scheduledId).filter(Boolean));
  }

  async function signIn() {
    const g = state.google;
    g.busy = true;
    g.error = null;
    renderAuth();
    try {
      await requestToken(g.cal ? "" : "consent");
      await loadCalendar();
    } catch (e) {
      g.error = e.message;
    } finally {
      g.busy = false;
      render();
    }
  }

  function signOut() {
    const g = state.google;
    if (g.token && window.google && google.accounts && google.accounts.oauth2) {
      google.accounts.oauth2.revoke(g.token, () => {});
    }
    g.token = null;
    g.expiresAt = 0;
    g.cal = null;
    g.added = new Set();
    g.error = null;
    storeRemove(STORE_GCAL);
    sessionSet(SESSION_TOKEN, null);
    render();
  }

  // ---------- staying connected ----------
  //
  // Google's browser sign-in gives a pass that lasts about an hour and can't be renewed
  // in the background, and a reloaded tab (browsers unload idle tabs) starts with none.
  // If you were signed in before, the first click anywhere asks Google again quietly
  // (no consent screen; at most a brief flash of its window). Browsers only allow
  // Google's window to open from a click, so it can't happen with no click at all.

  let reconnectArmed = false;

  function wantsReconnect() {
    return storeGet(STORE_GCAL) === "1" && !signedIn() && !state.google.busy && !!CFG.googleClientId;
  }

  function armReconnect() {
    if (reconnectArmed || !wantsReconnect()) return;
    reconnectArmed = true;
    document.addEventListener("click", (e) => {
      reconnectArmed = false;
      if (e.target.closest && e.target.closest("#auth")) return; // the sign-in button does this itself
      if (wantsReconnect()) reconnect();
    }, { capture: true, once: true });
  }

  async function reconnect() {
    const g = state.google;
    g.busy = true;
    g.error = null;
    renderAuth();
    try {
      await requestToken("");
      await loadCalendar();
    } catch (e) {
      g.error = e.message;
    } finally {
      g.busy = false;
      render(true);
      armReconnect();
    }
  }

  function restoreTabToken() {
    if (!CFG.keepTokenInTab) return false;
    try {
      const saved = JSON.parse(sessionGet(SESSION_TOKEN) || "null");
      if (saved && saved.t && Date.now() < saved.e) {
        state.google.token = saved.t;
        state.google.expiresAt = saved.e;
        return true;
      }
    } catch (e) { /* ignore */ }
    sessionSet(SESSION_TOKEN, null);
    return false;
  }

  // Insert a venue event into the primary calendar.
  async function addToCalendar(ev) {
    const tz = currentCity().tz;
    const desc = [ev.description, ev.url].filter(Boolean).join("\n\n");
    const where = ev.location && ev.location !== ev.venue ? `${ev.venue}, ${ev.location}` : ev.venue;
    const body = {
      summary: ev.title,
      location: where,
      description: desc,
      reminders: { useDefault: false, overrides: [] },
      extendedProperties: { private: { [PRIVATE_KEY]: ev.id } },
      source: safeHref(ev.url) ? { title: ev.venue, url: ev.url } : undefined,
    };
    if (ev.all_day) {
      const s = ev.start.slice(0, 10);
      const e = ev.end ? ev.end.slice(0, 10) : addDays(s, 1);
      body.start = { date: s };
      body.end = { date: e > s ? e : addDays(s, 1) };
    } else {
      const startMs = Date.parse(ev.start);
      const endMs = ev.end ? Date.parse(ev.end) : startMs + CFG.addDefaultMinutes * 60000;
      body.start = { dateTime: new Date(startMs).toISOString(), timeZone: tz };
      body.end = { dateTime: new Date(endMs).toISOString(), timeZone: tz };
    }
    const created = await gapi(CAL_API, { method: "POST", body: JSON.stringify(body) });
    const item = toCalItem(created, tz);
    state.google.cal = (state.google.cal || []).concat(item);
    state.google.added.add(ev.id);
  }

  // ---------- rendering ----------

  function renderAuth() {
    const box = document.getElementById("auth");
    box.replaceChildren();
    const g = state.google;
    if (!CFG.googleClientId) return;

    if (g.busy) {
      box.appendChild(el("span", "auth-note", "Connecting…"));
      return;
    }
    if (g.cal && signedIn()) {
      const out = el("button", "signin", "Sign out");
      out.type = "button";
      out.addEventListener("click", signOut);
      box.appendChild(out);
      return;
    }
    const b = el("button", "signin", storeGet(STORE_GCAL) === "1" ? "Reconnect calendar" : "Sign in with Google");
    b.type = "button";
    b.addEventListener("click", signIn);
    box.appendChild(b);
  }

  function renderCityBanner() {
    const banner = document.getElementById("cal-banner");
    banner.replaceChildren();
    const g = state.google;
    if (!CFG.googleClientId) {
      banner.hidden = true;
      return;
    }
    let msg = null;
    if (g.error) msg = g.error;
    else if (storeGet(STORE_GCAL) === "1" && !signedIn()) msg = "Click anywhere on the page to reconnect your calendar.";
    else if (!g.cal) msg = "Sign in with Google to see your calendar and add events to it.";
    banner.hidden = !msg;
    if (msg) {
      banner.appendChild(el("span", null, msg));
      banner.classList.toggle("error", !!g.error);
    }
  }

  function renderCitySwitch() {
    const nav = document.getElementById("city-switch");
    nav.replaceChildren();
    for (const c of knownCities()) {
      const b = el("button", "city", c.name);
      b.type = "button";
      b.setAttribute("aria-pressed", String(c.key === state.city));
      b.addEventListener("click", () => {
        if (state.city === c.key) return;
        state.city = c.key;
        storeSet(STORE_CITY, c.key);
        render();
      });
      nav.appendChild(b);
    }
  }

  function placeBlock(b, piece, bandStartMin) {
    const px = CFG.pxPerMinute;
    const height = Math.max(CFG.minBlockPx, (piece.e - piece.s) * px);
    b.style.top = `${(piece.s - bandStartMin) * px}px`;
    b.style.height = `${height - 1}px`;
    b.style.left = `calc(${(piece.left * 100).toFixed(3)}% + 1px)`;
    b.style.width = `calc(${(piece.width * 100).toFixed(3)}% - 3px)`;
    b.style.zIndex = String(piece.z);
    if (piece.nested) b.classList.add("nested");
    if (height < 34) b.classList.add("short");
    return height;
  }

  function renderBlock(piece, bandStartMin) {
    const ev = piece.ev;
    const b = el("button", `block ${kindClass(ev.kind)}`);
    b.type = "button";
    const height = placeBlock(b, piece, bandStartMin);

    const line1 = el("span", "b-line1");
    line1.appendChild(el("span", "b-time", piece.contStart ? "cont." : fmtMin(piece.s)));
    line1.appendChild(el("span", "b-title", ev.title));
    b.appendChild(line1);
    if (height >= 40) b.appendChild(el("span", "b-venue", ev.venue));
    if (state.google.added.has(ev.id)) {
      b.classList.add("added");
      b.appendChild(el("span", "b-check", "✓"));
    }

    b.setAttribute("aria-label", `${ev.title}, ${timeRange(ev)}, ${ev.venue}`);
    b.addEventListener("click", (e) => { e.stopPropagation(); openPopover(ev, b); });
    return b;
  }

  function renderCalBlock(piece, bandStartMin) {
    const ev = piece.ev;
    const b = el("button", "block cal");
    b.type = "button";
    b.style.setProperty("--gc", ev.color);
    if (ev.declined) b.classList.add("declined");
    const height = placeBlock(b, piece, bandStartMin);

    const range = piece.contStart ? `until ${fmtMin(piece.e)}` : `${fmtMin(piece.s)} – ${fmtMin(wall(ev.end).min)}`;
    if (height < 40) {
      const line = el("span", "b-line1");
      line.appendChild(el("span", "b-title", ev.title));
      line.appendChild(el("span", "b-time-inline", range));
      b.appendChild(line);
    } else {
      b.appendChild(el("span", "b-title b-title-wrap", ev.title));
      b.appendChild(el("span", "b-venue", range));
      if (ev.location && height >= 56) b.appendChild(el("span", "b-venue", ev.location));
    }
    b.setAttribute("aria-label", `${ev.title}, ${timeRange(ev)}${ev.location ? ", " + ev.location : ""}`);
    b.addEventListener("click", (e) => { e.stopPropagation(); openCalPopover(ev, b); });
    return b;
  }

  function renderAllDayChip(ev) {
    const b = el("button", `chip ${kindClass(ev.kind)}`);
    b.type = "button";
    b.appendChild(el("span", "b-title", ev.title));
    b.appendChild(el("span", "b-venue", ev.venue));
    if (state.google.added.has(ev.id)) b.appendChild(el("span", "b-check", "✓"));
    b.setAttribute("aria-label", `${ev.title}, ${timeRange(ev)}, ${ev.venue}`);
    b.addEventListener("click", (e) => { e.stopPropagation(); openPopover(ev, b); });
    return b;
  }

  function renderCalChip(ev) {
    const b = el("button", "chip cal");
    b.type = "button";
    b.style.setProperty("--gc", ev.color);
    if (ev.declined) b.classList.add("declined");
    b.appendChild(el("span", "b-title", ev.title));
    b.setAttribute("aria-label", `${ev.title}, ${timeRange(ev)}`);
    b.addEventListener("click", (e) => { e.stopPropagation(); openCalPopover(ev, b); });
    return b;
  }

  const EMPTY_DAY = { allDay: [], timed: [] };

  function renderBand(date, today, left, right, calOn) {
    const band = el("section", "band");
    band.dataset.date = date;

    const [rel, label] = dayHeading(date, today);
    const h = el("h2", "band-head");
    if (rel) h.appendChild(el("span", "band-rel", rel));
    h.appendChild(el("span", "band-date", label));
    band.appendChild(h);

    // All-day strip, each side on its own.
    if (left.allDay.length || right.allDay.length) {
      const strip = el("div", "strip");
      strip.appendChild(el("div", "gutter strip-label", "all day"));
      const l = el("div", "strip-col");
      left.allDay.forEach((p) => l.appendChild(renderAllDayChip(p.ev)));
      const r = el("div", "strip-col strip-cal");
      right.allDay.forEach((p) => r.appendChild(renderCalChip(p.ev)));
      strip.appendChild(l);
      strip.appendChild(r);
      band.appendChild(strip);
    }

    const timed = left.timed.concat(right.timed);
    if (timed.length) {
      let first = DAY_MIN;
      let last = 0;
      for (const p of timed) {
        first = Math.min(first, p.s);
        last = Math.max(last, p.e, p.s + CFG.minBlockPx / CFG.pxPerMinute);
      }
      const startH = Math.floor(first / 60);
      const endH = Math.min(24, Math.max(startH + 1, Math.ceil(last / 60)));
      const bandStart = startH * 60;

      const grid = el("div", "grid");
      grid.style.height = `${(endH - startH) * 60 * CFG.pxPerMinute}px`;
      grid.style.setProperty("--hour-px", `${60 * CFG.pxPerMinute}px`);

      const gutter = el("div", "gutter hours");
      for (let hr = startH; hr < endH; hr++) {
        const lab = el("span", "hour", fmtHour(hr));
        lab.style.top = `${(hr - startH) * 60 * CFG.pxPerMinute}px`;
        gutter.appendChild(lab);
      }
      grid.appendChild(gutter);

      const lc = el("div", "col col-events");
      for (const piece of layoutColumn(left.timed)) lc.appendChild(renderBlock(piece, bandStart));
      grid.appendChild(lc);

      const rc = el("div", `col col-cal${calOn ? "" : " off"}`);
      for (const piece of layoutColumn(right.timed)) rc.appendChild(renderCalBlock(piece, bandStart));
      grid.appendChild(rc);

      if (date === today) {
        const nowMin = wall(wallIso(Date.now(), currentCity().tz)).min;
        if (nowMin >= bandStart && nowMin <= endH * 60) {
          const line = el("div", "now-line");
          line.style.top = `${(nowMin - bandStart) * CFG.pxPerMinute}px`;
          grid.appendChild(line);
        }
      }
      band.appendChild(grid);
    }
    return band;
  }

  function renderDays(keepPopover) {
    const main = document.getElementById("days");
    main.replaceChildren();
    if (!keepPopover) closePopover();

    if (state.loadError) {
      main.appendChild(el("p", "notice", "Couldn't load events. " + state.loadError));
      return;
    }
    const city = currentCity();
    const venueEvents = (state.events.events || []).filter((e) => e.city === city.key);
    const cal = state.google.cal || [];

    const today = todayIn(city.tz);
    const lastDay = addDays(today, (CFG.daysAhead || 14) - 1);
    const now = Date.now();
    const leftByDay = piecesByDay(venueEvents, today, lastDay, now, true);
    const rightByDay = piecesByDay(cal, today, lastDay, now, false);

    if (!venueEvents.length) {
      const msg = (state.events.cities || []).some((c) => c.key === city.key)
        ? `No upcoming events collected for ${city.name} yet.`
        : `${city.name} isn't collected yet. It will appear here once its venues are added.`;
      main.appendChild(el("p", "notice", msg));
    }

    let shown = 0;
    for (let d = today; d <= lastDay; d = addDays(d, 1)) {
      const left = leftByDay.get(d) || EMPTY_DAY;
      const right = rightByDay.get(d) || EMPTY_DAY;
      if (!left.allDay.length && !left.timed.length && !right.allDay.length && !right.timed.length) continue;
      main.appendChild(renderBand(d, today, left, right, !!state.google.cal));
      shown++;
    }
    if (!shown && venueEvents.length) {
      main.appendChild(el("p", "notice", `Nothing coming up in ${city.name} in the next ${CFG.daysAhead} days.`));
    }
  }

  function renderFooter() {
    const f = document.getElementById("footer");
    f.replaceChildren();
    const gen = state.events && state.events.generated_at;
    const tz = currentCity().tz;
    const when = gen
      ? new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
          .format(new Date(gen))
      : "not yet";
    f.appendChild(el("p", "updated", `Last updated ${when}`));

    const sources = (state.status && state.status.sources) || {};
    const failed = Object.entries(sources).filter(([, s]) => s.result === "failed");
    if (failed.length) {
      const wrap = el("div", "failed");
      wrap.appendChild(el("p", "failed-head", `${failed.length} source${failed.length > 1 ? "s" : ""} failed on the last run:`));
      const ul = el("ul");
      for (const [key, s] of failed) {
        const li = el("li");
        li.appendChild(el("strong", null, s.name || key));
        if (s.error) li.appendChild(el("span", "err", " — " + s.error));
        ul.appendChild(li);
      }
      wrap.appendChild(ul);
      f.appendChild(wrap);
    }
  }

  function render(keepPopover) {
    renderCitySwitch();
    renderAuth();
    renderCityBanner();
    if (!state.events && !state.loadError) return;
    renderDays(keepPopover);
    renderFooter();
  }

  // ---------- popovers ----------

  const pop = () => document.getElementById("popover");

  function closePopover() {
    const p = pop();
    if (!p.hidden) {
      p.hidden = true;
      p.replaceChildren();
    }
  }

  function startPopover(cls) {
    const p = pop();
    p.replaceChildren();
    p.className = `popover ${cls}`;
    p.style.removeProperty("--gc");
    const close = el("button", "pop-close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Close");
    close.addEventListener("click", closePopover);
    p.appendChild(close);
    return p;
  }

  function showPopover(p, anchor) {
    p.hidden = false;
    // Place next to the block, kept inside the viewport.
    const r = anchor.getBoundingClientRect();
    const pw = p.offsetWidth;
    const ph = p.offsetHeight;
    const vw = document.documentElement.clientWidth;
    const vh = window.innerHeight;
    let left = r.right + 8;
    if (left + pw > vw - 8) left = Math.max(8, r.left - pw - 8);
    if (left < 8 || vw < 640) left = Math.max(8, Math.min(vw - pw - 8, r.left));
    let top = r.top;
    if (vw < 640) top = r.bottom + 6;
    if (top + ph > vh - 8) top = Math.max(8, vh - ph - 8);
    // Absolute (page) coordinates, so the popover scrolls along with its block.
    p.style.left = `${left + window.scrollX}px`;
    p.style.top = `${top + window.scrollY}px`;
    p.querySelector(".pop-close").focus({ preventScroll: true });
  }

  function addButtonState(btn, ev) {
    const g = state.google;
    btn.classList.remove("done", "busy");
    btn.disabled = false;
    if (g.added.has(ev.id)) {
      btn.textContent = "✓";
      btn.classList.add("done");
      btn.disabled = true;
      btn.title = "On your calendar";
      btn.setAttribute("aria-label", "Already on your calendar");
    } else if (!g.cal) {
      btn.textContent = "+";
      btn.disabled = true;
      btn.title = "Sign in with Google to add this to your calendar";
      btn.setAttribute("aria-label", "Add to my calendar (sign in first)");
    } else {
      btn.textContent = "+";
      btn.title = "Add to my calendar";
      btn.setAttribute("aria-label", "Add to my calendar");
    }
  }

  function openPopover(ev, anchor) {
    const p = startPopover(kindClass(ev.kind));

    p.appendChild(el("h3", "pop-title", ev.title));
    p.appendChild(el("p", "pop-time", timeRange(ev)));
    const venue = el("p", "pop-venue", ev.venue);
    if (ev.location && ev.location !== ev.venue) venue.appendChild(el("span", "pop-loc", " · " + ev.location));
    p.appendChild(venue);
    const price = priceText(ev.price);
    if (price) p.appendChild(el("p", "pop-price", price));
    if (ev.description) p.appendChild(el("p", "pop-desc", ev.description));
    if (ev.also_listed_by && ev.also_listed_by.length) {
      p.appendChild(el("p", "pop-also", "Also listed by " + ev.also_listed_by.join(", ")));
    }

    const actions = el("div", "pop-actions");
    const href = safeHref(ev.url);
    if (href) {
      const a = el("a", "pop-link", "Event page ↗");
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      actions.appendChild(a);
    } else {
      actions.appendChild(el("span"));
    }
    const msg = el("span", "pop-msg");
    actions.appendChild(msg);
    const add = el("button", "add");
    add.type = "button";
    addButtonState(add, ev);
    add.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (add.disabled || add.classList.contains("busy")) return;
      add.classList.add("busy");
      add.textContent = "…";
      msg.textContent = "";
      try {
        await ensureToken();
        // Re-check in case it was added from another tab since the page loaded.
        if (!state.google.added.has(ev.id)) await addToCalendar(ev);
        addButtonState(add, ev);
        msg.textContent = "Added";
        render(true);
      } catch (err) {
        addButtonState(add, ev);
        msg.textContent = err.message;
        msg.classList.add("error");
        renderAuth();
        renderCityBanner();
      }
    });
    actions.appendChild(add);
    p.appendChild(actions);
    showPopover(p, anchor);
  }

  function openCalPopover(ev, anchor) {
    const p = startPopover("cal-pop");
    p.style.setProperty("--gc", ev.color);
    p.appendChild(el("h3", "pop-title", ev.title));
    p.appendChild(el("p", "pop-time", timeRange(ev)));
    if (ev.location) p.appendChild(el("p", "pop-venue", ev.location));
    if (ev.declined) p.appendChild(el("p", "pop-also", "You declined this event."));
    const href = safeHref(ev.link);
    if (href) {
      const a = el("a", "pop-link", "Open in Google Calendar ↗");
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      p.appendChild(a);
    }
    showPopover(p, anchor);
  }

  document.addEventListener("click", (e) => {
    const p = pop();
    if (!p.hidden && !p.contains(e.target)) closePopover();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePopover(); });

  // ---------- data loading ----------

  async function fetchJson(name) {
    let lastErr = null;
    for (const base of CFG.dataBases) {
      try {
        const r = await fetch(base + name, { cache: "no-cache" });
        if (r.ok) return await r.json();
        lastErr = new Error(`${name}: HTTP ${r.status}`);
      } catch (e) {
        lastErr = e;
      }
    }
    throw lastErr || new Error(`${name} not found`);
  }

  async function init() {
    state.city = storeGet(STORE_CITY) || CFG.defaultCity;
    render();
    try {
      state.events = await fetchJson("events.json");
    } catch (e) {
      state.loadError = e.message;
    }
    try {
      state.status = await fetchJson("status.json");
    } catch (e) {
      state.status = null;
    }
    if (!knownCities().some((c) => c.key === state.city)) state.city = CFG.defaultCity;
    render();
    if (restoreTabToken()) {
      try {
        await loadCalendar();
      } catch (e) {
        state.google.error = e.message;
      }
      render();
    }
    armReconnect();
    // Notice an expired pass while the page sits open, and reconnect on the next click.
    setInterval(() => {
      if (state.google.cal && !signedIn() && !state.google.busy) {
        renderAuth();
        renderCityBanner();
        armReconnect();
      }
    }, 60_000);
  }

  // Exposed for tests.
  window.__eventScheduler = { layoutColumn, piecesByDay, wall, toCalItem, state };

  init();
})();
