/* Event Scheduler page. Plain JS, no build step.
 *
 * Safety: every piece of scraped text goes in with textContent, never innerHTML,
 * and only http/https links are rendered (SPEC.md section 6, Safety).
 */
(function () {
  "use strict";

  const CFG = window.APP_CONFIG;
  const STORE_CITY = "es.city";
  const DAY_MIN = 24 * 60;

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

  // Event times are ISO strings already in the city's zone ("2026-11-04T18:30:00-05:00"),
  // so the wall-clock date and minutes can be read straight off the string.
  function wall(iso) {
    return { date: iso.slice(0, 10), min: Number(iso.slice(11, 13)) * 60 + Number(iso.slice(14, 16)) };
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
    const parts = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" })
      .formatToParts(new Date());
    const get = (t) => parts.find((p) => p.type === t).value;
    return `${get("year")}-${get("month")}-${get("day")}`;
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
    if (ev.all_day) {
      const lastDay = ev.end ? addDays(wall(ev.end).date, -1) : s.date;
      if (lastDay === s.date) return fmtDate(s.date, { weekday: "short", month: "short", day: "numeric" }) + " · all day";
      return fmtDate(s.date, { month: "short", day: "numeric" }) + " – " + fmtDate(lastDay, { month: "short", day: "numeric" });
    }
    const day = fmtDate(s.date, { weekday: "short", month: "short", day: "numeric" });
    if (!ev.end) return `${day} · ${fmtMin(s.min)}`;
    const e = wall(ev.end);
    if (e.date === s.date) return `${day} · ${fmtMin(s.min)} – ${fmtMin(e.min)}`;
    return `${day} ${fmtMin(s.min)} – ${fmtDate(e.date, { weekday: "short", month: "short", day: "numeric" })} ${fmtMin(e.min)}`;
  }

  function priceText(price) {
    if (!price) return null;
    if (price.text) return price.text;
    if (price.free === true) return "Free";
    if (price.min != null) return price.min === 0 ? "Free" : `From $${price.min}`;
    return null;
  }

  // ---------- turning events into per-day pieces ----------

  // Returns Map(date -> {allDay: [...], timed: [...]}), each piece {ev, s, e} in minutes of that day.
  function piecesByDay(events, firstDay, lastDay, nowMs) {
    const days = new Map();
    const slot = (d) => {
      if (!days.has(d)) days.set(d, { allDay: [], timed: [] });
      return days.get(d);
    };
    const inRange = (d) => d >= firstDay && d <= lastDay;

    for (const ev of events) {
      const s = wall(ev.start);
      const endIso = ev.end;
      // Hide what has already ended (the data file can be a few days old).
      const endMs = endIso ? Date.parse(endIso)
        : Date.parse(ev.start) + (ev.all_day ? DAY_MIN : CFG.noEndDisplayMinutes) * 60000;
      if (endMs <= nowMs) continue;

      const e = endIso ? wall(endIso) : null;
      const longTimed = !ev.all_day && endIso && Date.parse(endIso) - Date.parse(ev.start) >= DAY_MIN * 60000;

      if (ev.all_day || longTimed) {
        // All-day and multi-day items go in the strip of every day they cover.
        let last = e ? e.date : s.date;
        if (ev.all_day && e && e.min === 0) last = addDays(e.date, -1);
        if (last < s.date) last = s.date;
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
        if (inRange(s.date)) slot(s.date).timed.push({ ev, s: s.min, e: DAY_MIN, contEnd: true });
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

  // ---------- rendering ----------

  const state = {
    city: null,
    events: null,
    status: null,
    loadError: null,
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

  function renderBlock(piece, bandStartMin) {
    const ev = piece.ev;
    const px = CFG.pxPerMinute;
    const top = (piece.s - bandStartMin) * px;
    const height = Math.max(CFG.minBlockPx, (piece.e - piece.s) * px);

    const b = el("button", `block ${kindClass(ev.kind)}${piece.nested ? " nested" : ""}`);
    b.type = "button";
    b.style.top = `${top}px`;
    b.style.height = `${height - 1}px`;
    b.style.left = `calc(${(piece.left * 100).toFixed(3)}% + 1px)`;
    b.style.width = `calc(${(piece.width * 100).toFixed(3)}% - 3px)`;
    b.style.zIndex = String(piece.z);
    if (height < 34) b.classList.add("short");

    const line1 = el("span", "b-line1");
    line1.appendChild(el("span", "b-time", piece.contStart ? "cont." : fmtMin(piece.s)));
    line1.appendChild(el("span", "b-title", ev.title));
    b.appendChild(line1);
    if (height >= 40) b.appendChild(el("span", "b-venue", ev.venue));

    b.setAttribute("aria-label", `${ev.title}, ${timeRange(ev)}, ${ev.venue}`);
    b.addEventListener("click", (e) => { e.stopPropagation(); openPopover(ev, b); });
    return b;
  }

  function renderAllDayChip(ev) {
    const b = el("button", `chip ${kindClass(ev.kind)}`);
    b.type = "button";
    b.appendChild(el("span", "b-title", ev.title));
    b.appendChild(el("span", "b-venue", ev.venue));
    b.setAttribute("aria-label", `${ev.title}, ${timeRange(ev)}, ${ev.venue}`);
    b.addEventListener("click", (e) => { e.stopPropagation(); openPopover(ev, b); });
    return b;
  }

  function renderBand(date, today, day) {
    const band = el("section", "band");
    band.dataset.date = date;

    const [rel, label] = dayHeading(date, today);
    const h = el("h2", "band-head");
    if (rel) h.appendChild(el("span", "band-rel", rel));
    h.appendChild(el("span", "band-date", label));
    band.appendChild(h);

    // All-day strip, each side on its own.
    if (day.allDay.length) {
      const strip = el("div", "strip");
      strip.appendChild(el("div", "gutter strip-label", "all day"));
      const left = el("div", "strip-col");
      day.allDay.forEach((p) => left.appendChild(renderAllDayChip(p.ev)));
      strip.appendChild(left);
      strip.appendChild(el("div", "strip-col strip-cal"));
      band.appendChild(strip);
    }

    if (day.timed.length) {
      let first = DAY_MIN;
      let last = 0;
      for (const p of day.timed) {
        first = Math.min(first, p.s);
        last = Math.max(last, Math.max(p.e, p.s + CFG.minBlockPx / CFG.pxPerMinute));
      }
      const startH = Math.floor(first / 60);
      const endH = Math.min(24, Math.max(startH + 1, Math.ceil(last / 60)));
      const bandStart = startH * 60;
      const heightPx = (endH - startH) * 60 * CFG.pxPerMinute;

      const grid = el("div", "grid");
      grid.style.height = `${heightPx}px`;
      grid.style.setProperty("--hour-px", `${60 * CFG.pxPerMinute}px`);

      const gutter = el("div", "gutter hours");
      for (let hr = startH; hr < endH; hr++) {
        const lab = el("span", "hour", fmtHour(hr));
        lab.style.top = `${(hr - startH) * 60 * CFG.pxPerMinute}px`;
        gutter.appendChild(lab);
      }
      grid.appendChild(gutter);

      const left = el("div", "col col-events");
      for (const piece of layoutColumn(day.timed)) left.appendChild(renderBlock(piece, bandStart));
      grid.appendChild(left);

      const right = el("div", "col col-cal");
      grid.appendChild(right);

      if (date === today) {
        const nowMin = wall(new Intl.DateTimeFormat("sv-SE", {
          timeZone: currentCity().tz, hour: "2-digit", minute: "2-digit", year: "numeric", month: "2-digit", day: "2-digit",
        }).format(new Date()).replace(" ", "T")).min;
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

  function renderDays() {
    const main = document.getElementById("days");
    main.replaceChildren();
    closePopover();

    if (state.loadError) {
      main.appendChild(el("p", "notice", "Couldn't load events. " + state.loadError));
      return;
    }
    const city = currentCity();
    const all = (state.events.events || []).filter((e) => e.city === city.key);
    if (!all.length) {
      const msg = (state.events.cities || []).some((c) => c.key === city.key)
        ? `No upcoming events collected for ${city.name} yet.`
        : `${city.name} isn't collected yet. It will appear here once its venues are added.`;
      main.appendChild(el("p", "notice", msg));
      return;
    }

    const today = todayIn(city.tz);
    const lastDay = addDays(today, (CFG.daysAhead || 14) - 1);
    const byDay = piecesByDay(all, today, lastDay, Date.now());
    let shown = 0;
    for (let d = today; d <= lastDay; d = addDays(d, 1)) {
      const day = byDay.get(d);
      if (!day || (!day.allDay.length && !day.timed.length)) continue; // nothing on either side
      main.appendChild(renderBand(d, today, day));
      shown++;
    }
    if (!shown) main.appendChild(el("p", "notice", `Nothing coming up in ${city.name} in the next ${CFG.daysAhead} days.`));
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

  function render() {
    renderCitySwitch();
    if (!state.events && !state.loadError) return;
    renderDays();
    renderFooter();
  }

  // ---------- popover ----------

  const pop = () => document.getElementById("popover");

  function closePopover() {
    const p = pop();
    if (!p.hidden) {
      p.hidden = true;
      p.replaceChildren();
    }
  }

  function openPopover(ev, anchor) {
    const p = pop();
    p.replaceChildren();
    p.className = `popover ${kindClass(ev.kind)}`;

    const close = el("button", "pop-close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Close");
    close.addEventListener("click", closePopover);
    p.appendChild(close);

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
    }
    const add = el("button", "add", "+");
    add.type = "button";
    add.disabled = true;
    add.title = "Sign in with Google to add this to your calendar";
    add.setAttribute("aria-label", "Add to my calendar");
    actions.appendChild(add);
    p.appendChild(actions);

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
    p.style.left = `${left}px`;
    p.style.top = `${top}px`;
    close.focus({ preventScroll: true });
  }

  document.addEventListener("click", (e) => {
    const p = pop();
    if (!p.hidden && !p.contains(e.target)) closePopover();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePopover(); });
  window.addEventListener("scroll", closePopover, { passive: true });

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
    const saved = storeGet(STORE_CITY);
    state.city = saved || CFG.defaultCity;
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
  }

  // Exposed for tests.
  window.__eventScheduler = { layoutColumn, piecesByDay, wall };

  init();
})();
