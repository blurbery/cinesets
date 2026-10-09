/* CineSets by blurbery (https://github.com/blurbery/cinesets). SPDX-License-Identifier: AGPL-3.0-or-later.
   Additional terms under AGPL-3.0 section 7 apply: see NOTICE. */
/* CineSets dashboard: turn collections on and off, design posters with live previews rendered by the
   CineSets server, save to the config file and run CineSets. Plain browser JavaScript, no build step. */
"use strict";

(() => {
  // ------------------------------------------------------------------ constants
  const SESSION_ENDED = "Your session ended. Sign in again to carry on; your unsaved changes are still here.";
  const UNREACHABLE = "Can't reach CineSets. Is it still running? Look in the terminal where it started, or its log: "
    + "docker compose logs cinesets-web on Docker, journalctl -u cinesets-web with systemd.";
  const OFFLINE = "Can't reach CineSets, so the dashboard keeps trying by itself and your unsaved changes stay here. "
    + "If it doesn't come back, check CineSets is running: the terminal where it started, docker compose logs "
    + "cinesets-web on Docker, or journalctl -u cinesets-web with systemd.";
  const OFFLINE_MS = [2000, 4000, 8000, 15000];
  const DEBOUNCE = 250;
  const GRID_DEBOUNCE = 350;
  const POLL_MS = 1500;
  const CENTRE_X = 0.5;
  const LEFT_X = 0.078;
  const SNAP = 0.02;
  const LAYER_KEYS = new Set(["sections", "overrides"]);
  const TABS = ["collections", "design", "lists", "grid"];
  const MDBLIST = "https://mdblist.com/lists/";
  const MAX_NEW_LISTS = 10;
  const CACHE_MAX = 40;     // full-size previews kept for the editor
  const TILE_MAX = 240;     // small previews kept for the strip and Preview all
  const HISTORY_MAX = 100;  // design steps Undo can go back
  const BURST_MS = 1000;    // changes to one setting this close together are one step to undo
  const INTRO_KEY = "cinesets-intro-done";

  const LABELS = {
    artwork: { fixed: "Fixed", random: "Random", mosaic: "Mosaic" },
    mosaic: { "2x2": "2 x 2", "3x3": "3 x 3" },
    shade: { light: "Light", medium: "Medium", dark: "Dark" },
    tint: { strong: "Strong", normal: "Normal", subtle: "Subtle", none: "None" },
    title: { gradient: "Gradient", solid: "Solid", white: "White" },
    align: { left: "Left", centre: "Centre" },
    case: { normal: "As written", upper: "Capitals" },
    text_shadow: { auto: "Auto", on: "On", off: "Off" },
    text: { gold: "Gold", white: "White", accent: "Accent" },
    logo: { standard: "Standard", alt: "Alternative", icon: "Icon" },
    logo_colour: { original: "Original", white: "White" },
  };
  const SETTING_NAMES = {
    accent: "accent colour", shade: "shade", tint: "tint", title: "title style", font: "font", align: "alignment", case: "capitals",
    label: "label", label_colour: "label colour", subtitle_colour: "subtitle colour",
    label_position: "label position", title_position: "title position", title_size: "title size", label_size: "label size",
    text_shadow: "text shadow", artwork: "artwork", mosaic: "mosaic grid", logo: "logo", logo_colour: "logo colours",
  };
  const LOGO_HINT = "Uses the alternative or icon where the service has one, otherwise its standard logo.";
  const LOGO_MISSING = "Downloaded by ./run.sh logos. Until then the poster shows the service's name.";
  const SIZE_SETTING = { title: "title_size", label: "label_size" };
  const SIZE_STEP = 0.05;
  const ICON = {
    chevron: '<svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    x: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  };

  // ------------------------------------------------------------------ small helpers
  const $ = (id) => document.getElementById(id);
  const clamp01 = (n) => Math.min(1, Math.max(0, Number(n) || 0));
  const round = (n, places) => {
    const f = 10 ** places;
    return Math.round(n * f) / f;
  };
  const cap = (s) => String(s).charAt(0).toUpperCase() + String(s).slice(1);
  const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));
  const isHex = (v) => typeof v === "string" && /^#[0-9a-f]{6}$/i.test(v);
  const has = (obj, k) => !!obj && Object.prototype.hasOwnProperty.call(obj, k);
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  /** JSON with sorted keys, so objects compare equal whatever order their keys arrived in. */
  function stable(v) {
    if (Array.isArray(v)) return "[" + v.map(stable).join(",") + "]";
    if (v && typeof v === "object") {
      return "{" + Object.keys(v).sort().filter((k) => v[k] !== undefined)
        .map((k) => JSON.stringify(k) + ":" + stable(v[k])).join(",") + "}";
    }
    return JSON.stringify(v === undefined ? null : v);
  }
  const same = (a, b) => stable(a) === stable(b);

  function setsEqual(a, b) {
    if (a.size !== b.size) return false;
    for (const k of a) if (!b.has(k)) return false;
    return true;
  }

  function listText(items) {
    return items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}` : items.join("");
  }

  /** Build an element. Never sets a style attribute (the page's CSP forbids inline styles). */
  function el(tag, props, children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v;
      else if (v === true) node.setAttribute(k, "");
      else node.setAttribute(k, String(v));
    }
    for (const c of [].concat(children === undefined ? [] : children)) {
      if (c !== null && c !== undefined && c !== false) node.append(c);
    }
    return node;
  }
  function svg(markup) {
    const t = document.createElement("template");
    t.innerHTML = markup.trim();
    return t.content.firstElementChild;
  }
  function announce(msg) {
    const live = $("sr-live");
    live.textContent = "";
    setTimeout(() => { live.textContent = msg; }, 30);
  }

  // ------------------------------------------------------------------ state
  const S = {
    gated: false,
    loaded: false,
    session: null,
    info: null,
    sections: [],
    byKey: new Map(),
    secByKey: new Map(),
    order: [],
    saved: { posters: null, collections: null, picks: new Set(), version: null, limits: null },
    posters: null,
    picks: new Set(),
    limits: null,
    lpSearch: "",
    lpOpen: new Set(),
    lpSearchClosed: new Set(),
    nc: { checked: null, accent: null, typeTouched: false },
    selected: null,
    mode: "section",
    editSec: null,
    posterKey: null,
    secSearch: "",
    listClosed: new Set(),
    tab: "design",
    colSearch: "",
    listSearch: "",
    colOpen: new Set(),
    colSearchClosed: new Set(),
    listSearchClosed: new Set(),
    dirty: false,
    saving: false,
    textDraft: null,
    textBusy: false,
    artBusy: false,
    chooser: null,
    dragging: null,
    cache: new Map(),
    tiles: new Map(),
    artRev: new Map(),
    history: { undo: [], redo: [], base: null, tag: null, at: 0, replaying: false },
    offline: { on: false, tries: 0, timer: null },
    preview: {
      seq: 0, applied: 0, boxesSeq: 0, timer: null, candidate: null,
      key: null, layout: null, boxes: { label: null, title: null }, draggable: true, streaming: false, art: null,
    },
    grid: { cards: new Map(), byEl: new Map(), order: [], observer: null, root: undefined, timer: null },
    strip: { sec: null, keys: [], cards: new Map(), hold: false, timer: null },
    run: {
      running: false, command: null, timer: null, shown: 0, exit: null,
      id: null, problems: 0, summary: null, stopped: null, lost: false,
    },
    ui: {
      cards: new Map(), ccRows: new Map(), dsecs: new Map(), drows: new Map(), dpicks: new Map(), dlistMode: null,
      controls: {}, logoCtx: null, sizes: new Map(), secSizes: new Map(), lpSecs: new Map(), lpRows: new Map(),
    },
  };
  const lane = { busy: false, editor: null };

  // ------------------------------------------------------------------ API
  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }

  /**
   * Call the CineSets API. Paths are relative ("api/info") so the dashboard also works behind a reverse
   * proxy on a sub-path. The session cookie is HttpOnly; the X-CineSets header guards against CSRF.
   * A 503 (server busy) is retried once after a second. A 401 drops back to the sign-in card unless
   * `quiet401` is set (sign-in itself handles its own 401).
   */
  async function api(path, opts) {
    const { method = "GET", body, raw = false, quiet401 = false } = opts || {};
    const headers = { "X-CineSets": "1" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let res;
    for (let attempt = 0; ; attempt++) {
      try {
        res = await fetch(path, {
          method, headers, cache: "no-store", credentials: "same-origin",
          body: body !== undefined ? JSON.stringify(body) : undefined,
        });
      } catch (e) {
        throw new ApiError(UNREACHABLE, 0);
      }
      if (res.status !== 503 || attempt > 0) break;
      await sleep(1000);
    }
    if (res.status === 401 && !quiet401) {
      showSignIn(S.loaded ? SESSION_ENDED : "");
      throw new ApiError("Please sign in again.", 401);
    }
    if (!res.ok) {
      let msg = `Something went wrong (error ${res.status}).`;
      try {
        const j = await res.json();
        if (j && j.error) msg = String(j.error);
      } catch (_) { /* not JSON */ }
      throw new ApiError(msg, res.status);
    }
    if (raw) return res;
    try {
      return await res.json();
    } catch (_) {
      throw new ApiError("CineSets sent a reply the dashboard couldn't read.", res.status);
    }
  }

  // ------------------------------------------------------------------ sign-in, errors, toasts, dialog
  function gateUp() {
    S.gated = true;
    clearTimeout(S.run.timer);
    clearTimeout(S.preview.timer);
    lane.editor = null;
    if (S.dragging) endDrag(null, true);
    if (S.chooser) closeChooser();
    const dlg = $("confirm");
    if (dlg.open) dlg.close();
    $("boot").hidden = true;
    $("app").hidden = true;
    $("gate").hidden = false;
  }

  /** A message with an optional Try again button, for when the dashboard can't load at all. */
  function showError(msg, retry) {
    gateUp();
    $("signin").hidden = true;
    $("gate-msg").hidden = false;
    $("gate-msg").textContent = msg;
    $("gate-retry").hidden = !retry;
  }

  /** The sign-in card. The app (and any unsaved edits) stays in memory underneath. */
  function showSignIn(note, error) {
    const already = S.gated && !$("signin").hidden;
    gateUp();
    $("gate-msg").hidden = true;
    $("gate-retry").hidden = true;
    $("signin").hidden = false;
    const n = $("signin-note");
    if (note || !already) {
      n.hidden = !note;
      n.textContent = note || "";
    }
    setSignInError(error || "");
    const input = $("signin-key");
    input.placeholder = S.session && S.session.password ? "Your password" : "The access key from the terminal";
    if (!already) input.value = "";
    setTimeout(() => input.focus(), 0);
  }

  function setSignInError(msg) {
    const err = $("signin-error");
    err.hidden = !msg;
    err.textContent = msg;
    $("signin-key").setAttribute("aria-invalid", msg ? "true" : "false");
  }

  async function submitSignIn(e) {
    e.preventDefault();
    const input = $("signin-key");
    const key = input.value.trim();
    if (!key) {
      setSignInError("Enter your access key or password.");
      input.focus();
      return;
    }
    const btn = $("signin-btn");
    btn.disabled = true;
    btn.classList.add("is-busy");
    try {
      await api("api/login", { method: "POST", body: { key }, quiet401: true });
      input.value = "";
      setSignInError("");
      await afterSignIn();
    } catch (err) {
      setSignInError(err.message || "That didn't work. Try again.");
      input.select();
    } finally {
      btn.disabled = false;
      btn.classList.remove("is-busy");
    }
  }

  async function afterSignIn() {
    if (!S.loaded) {
      await startApp();
      return;
    }
    // back from a lapsed session: pick up where the user left off
    S.gated = false;
    $("gate").hidden = true;
    $("app").hidden = false;
    queueEditorJob();
    gridKick(30);
    if (stripActive()) stripKick(200);
    pollRun();
  }

  async function signOut() {
    try {
      await api("api/logout", { method: "POST", body: {}, quiet401: true });
    } catch (e) {
      if (e.status !== 401) {
        fail(e, "Couldn't sign out");
        return;
      }
    }
    showSignIn(unsaved() ? "You're signed out. Your unsaved changes are kept here until you close the tab." : "You're signed out.");
  }

  /**
   * A message in the corner. Errors stay until they're dismissed; the rest go after a few seconds, or a little
   * longer with an action button (like Undo), and wait while the pointer or focus is on them.
   */
  function toast(msg, kind, ms, action) {
    kind = kind || "info";
    const box = $("toasts");
    for (const t of box.children) {
      if (t.dataset.msg === msg && !t.classList.contains("is-leaving")) return;
    }
    const x = el("button", { class: "toast-x", type: "button", "aria-label": "Dismiss", html: ICON.x });
    const t = el("div", { class: `toast toast-${kind}`, "data-msg": msg }, [el("span", { text: msg })]);
    const sticky = kind === "error";
    let timer = null;
    const close = () => {
      clearTimeout(timer);
      t.classList.add("is-leaving");
      setTimeout(() => t.remove(), 220);
    };
    const later = (wait) => {
      clearTimeout(timer);
      if (!sticky) timer = setTimeout(close, wait);
    };
    if (action) {
      const act = el("button", { class: "toast-act", type: "button" }, action.label);
      act.addEventListener("click", () => {
        close();
        action.run();
      });
      t.append(act);
    }
    t.append(x);
    x.addEventListener("click", close);
    t.addEventListener("mouseenter", () => clearTimeout(timer));
    t.addEventListener("mouseleave", () => { if (!t.contains(document.activeElement)) later(2500); });
    t.addEventListener("focusin", () => clearTimeout(timer));
    t.addEventListener("focusout", (e) => { if (!t.contains(e.relatedTarget)) later(2500); });
    box.append(t);
    while (box.children.length > 4) box.firstElementChild.remove();
    later(ms || (action ? 10000 : 4000));
  }

  function fail(e, prefix) {
    if (!e || e.status === 401 || S.gated) return;
    if (e.status === 0) {
      goOffline();
      return;
    }
    const msg = e.message || String(e);
    toast(prefix ? `${prefix}: ${msg}` : msg, "error");
  }

  // ---- when CineSets can't be reached: one banner that keeps trying by itself, instead of a toast each time
  function goOffline() {
    if (S.offline.on || S.gated || !S.loaded) return;
    S.offline.on = true;
    S.offline.tries = 0;
    clearTimeout(S.run.timer);
    $("offline-text").textContent = OFFLINE;
    $("offline").hidden = false;
    retryLater();
  }

  function retryLater() {
    clearTimeout(S.offline.timer);
    S.offline.timer = setTimeout(reconnect, OFFLINE_MS[Math.min(S.offline.tries, OFFLINE_MS.length - 1)]);
  }

  async function reconnect() {
    clearTimeout(S.offline.timer);
    if (!S.offline.on) return;
    S.offline.tries++;
    const btn = $("offline-retry");
    btn.disabled = true;
    try {
      await api("api/session", { quiet401: true });
    } catch (e) {
      if (e.status === 0) {
        retryLater();
        return;
      }
    } finally {
      btn.disabled = false;
    }
    S.offline.on = false;
    $("offline").hidden = true;
    toast("CineSets is back.", "ok");
    // carry on: the run log, then any previews that didn't arrive
    pollRun();
    queueEditorJob();
    gridKick(30);
    if (stripActive()) stripKick(200);
  }

  /**
   * A question with Cancel and OK. With `alt`, a third button as well, and it resolves to "ok", "alt" or ""
   * (cancelled); without, to true or false.
   */
  function confirmDialog({ title, text, ok, alt, danger }) {
    const d = $("confirm");
    if (typeof d.showModal !== "function") {
      const yes = window.confirm(`${title}\n\n${text}`);
      return Promise.resolve(alt ? (yes ? "ok" : "") : yes);
    }
    return new Promise((resolve) => {
      $("confirm-title").textContent = title;
      $("confirm-text").textContent = text;
      const okBtn = $("confirm-ok");
      okBtn.textContent = ok || "OK";
      okBtn.className = "btn " + (danger ? "btn-danger" : "btn-primary");
      const altBtn = $("confirm-alt");
      altBtn.hidden = !alt;
      altBtn.textContent = alt || "";
      d.returnValue = "";
      const onClose = () => {
        d.removeEventListener("close", onClose);
        const v = d.returnValue;
        resolve(alt ? (v === "ok" || v === "alt" ? v : "") : v === "ok");
      };
      d.addEventListener("close", onClose);
      d.showModal();
      $("confirm-cancel").focus();
    });
  }

  // ------------------------------------------------------------------ poster settings: all posters, then section, then collection
  function withDefaults(p) {
    const out = { ...clone(S.info.defaults || {}), ...clone(p || {}) };
    for (const k of LAYER_KEYS) {
      if (!out[k] || typeof out[k] !== "object" || Array.isArray(out[k])) out[k] = {};
    }
    return out;
  }

  function normValue(k, v) {
    if (k === "title_size" && typeof v === "number") return round(v, 2);
    if ((k === "label_position" || k === "title_position") && Array.isArray(v)) {
      return v.slice(0, 2).map((n) => round(clamp01(n), 3));
    }
    if (isHex(v)) return v.toLowerCase();
    if (Array.isArray(v)) return v.map((x) => (isHex(x) ? x.toLowerCase() : x));
    return v;
  }

  function cleanLayer(map) {
    const out = {};
    for (const [id, o] of Object.entries(map || {})) {
      if (!o || typeof o !== "object" || Array.isArray(o)) continue;
      const clean = {};
      for (const [k, v] of Object.entries(o)) clean[k] = normValue(k, v);
      if (Object.keys(clean).length) out[id] = clean;
    }
    return out;
  }

  /** A clean copy: rounded numbers, lower-case colours, no empty objects in the layers. */
  function normalisePosters(p) {
    const out = {};
    for (const k of Object.keys(p)) if (!LAYER_KEYS.has(k)) out[k] = normValue(k, p[k]);
    out.sections = cleanLayer(p.sections);
    out.overrides = cleanLayer(p.overrides);
    return out;
  }

  function globals() {
    const g = { ...S.posters };
    for (const k of LAYER_KEYS) delete g[k];
    return g;
  }
  const sectionOf = (key) => {
    const c = key && S.byKey.get(key);
    return c ? c.section : null;
  };
  const secOwn = (sec) => (sec && S.posters.sections[sec]) || {};
  const ownOf = (key) => (key && S.posters.overrides[key]) || {};
  const effective = (key) => ({ ...globals(), ...secOwn(sectionOf(key)), ...ownOf(key) });

  /** The layer edits go to: a section in Whole section mode, one poster in Each poster mode, or null for every poster. */
  function scopeLayer() {
    if (S.mode === "poster") return S.selected ? { kind: "overrides", id: S.selected } : null;
    return S.editSec ? { kind: "sections", id: S.editSec } : null;
  }
  /** What the layer being edited inherits from the layers above it. */
  function parentValues() {
    if (S.mode === "poster" && S.selected) return { ...globals(), ...secOwn(sectionOf(S.selected)) };
    return globals();
  }
  /** The values in effect for what is being edited. */
  function scopeValues() {
    if (S.mode === "poster") return S.selected ? effective(S.selected) : globals();
    return S.editSec ? { ...globals(), ...secOwn(S.editSec) } : globals();
  }
  function ownAtScope() {
    const l = scopeLayer();
    return l ? S.posters[l.kind][l.id] || {} : null;
  }
  function shown(setting) {
    return scopeValues()[setting];
  }
  const defaults = () => (S.info && S.info.defaults) || {};
  /** Every section: the settings for every poster that differ from the defaults. */
  function changedGlobals() {
    const d = defaults();
    return Object.keys(d).filter((k) => !LAYER_KEYS.has(k) && has(S.posters, k) && !same(normValue(k, S.posters[k]), normValue(k, d[k])));
  }

  function applySetting(name, value) {
    value = normValue(name, value);
    const l = scopeLayer();
    if (l) {
      const store = S.posters[l.kind];
      const own = { ...(store[l.id] || {}) };
      // a value that matches what this layer inherits is not kept as its own
      if (same(value, parentValues()[name])) delete own[name];
      else own[name] = value;
      if (Object.keys(own).length) store[l.id] = own;
      else delete store[l.id];
    } else {
      S.posters[name] = value;
    }
  }

  function setSetting(name, value, opts) {
    applySetting(name, value);
    settingsChanged({ tag: name, ...opts });
  }

  /** Reset one setting: back to inheriting it for a section or poster, or back to the default for every poster. */
  function inherit(name) {
    const l = scopeLayer();
    const label = cap(SETTING_NAMES[name] || name);
    if (!l) {
      const d = defaults();
      if (!has(d, name)) return;
      S.posters[name] = clone(d[name]);
      settingsChanged({ delay: 0 });
      announce(`${label} is back to the default.`);
      return;
    }
    const store = S.posters[l.kind];
    const own = { ...(store[l.id] || {}) };
    delete own[name];
    if (Object.keys(own).length) store[l.id] = own;
    else delete store[l.id];
    settingsChanged({ delay: 0 });
    announce(`${label} now comes from ${l.kind === "sections" ? "Every section" : "the section"}.`);
  }

  function resetScope() {
    const l = scopeLayer();
    let msg;
    if (!l) {
      const d = defaults();
      for (const k of Object.keys(d)) if (!LAYER_KEYS.has(k)) S.posters[k] = clone(d[k]);
      msg = "Every poster is back to the defaults. Sections and posters with their own settings keep them.";
    } else {
      delete S.posters[l.kind][l.id];
      msg = l.kind === "sections" ? "This section's own design settings were cleared." : "This poster's own design settings were cleared.";
    }
    settingsChanged({ delay: 0 });
    undoToast(msg);
  }

  // ---- undo and redo for design edits: snapshots of the poster settings
  /** Start the history again from the settings as they are now (after loading or reloading them). */
  function historyReset() {
    const h = S.history;
    h.undo = [];
    h.redo = [];
    h.base = snapshot();
    h.tag = null;
    h.at = 0;
    syncHistory();
  }

  /** After a design edit, keep the settings from before it. A burst of changes to one setting (a slider being
      dragged, a colour being picked, arrow keys on a text box) is one step. */
  function record(tag) {
    const h = S.history;
    if (h.replaying || !h.base || !S.posters) return;
    const now = snapshot();
    if (same(now, h.base)) return;
    const t = Date.now();
    if (!tag || tag !== h.tag || t - h.at > BURST_MS) {
      h.undo.push(h.base);
      if (h.undo.length > HISTORY_MAX) h.undo.shift();
    }
    h.redo = [];
    h.base = now;
    h.tag = tag || null;
    h.at = t;
    syncHistory();
  }

  function restorePosters(p, word) {
    const h = S.history;
    h.replaying = true;
    try {
      S.posters = clone(p);
      h.base = snapshot();
      h.tag = null;
      S.preview.boxesSeq = S.preview.seq + 1;
      settingsChanged({ delay: 0 });
    } finally {
      h.replaying = false;
    }
    syncHistory();
    announce(word);
  }

  function undo() {
    const h = S.history;
    if (!h.undo.length || !S.posters) return;
    h.redo.push(snapshot());
    restorePosters(h.undo.pop(), "Undone.");
  }

  function redo() {
    const h = S.history;
    if (!h.redo.length || !S.posters) return;
    h.undo.push(snapshot());
    restorePosters(h.redo.pop(), "Redone.");
  }

  function syncHistory() {
    $("undo-btn").disabled = !S.history.undo.length;
    $("redo-btn").disabled = !S.history.redo.length;
  }

  /** A toast with Undo for a reset: it steps back only if nothing else has changed since. */
  function undoToast(msg) {
    const after = snapshot();
    toast(msg, "info", 0, {
      label: "Undo",
      run: () => {
        if (same(snapshot(), after)) undo();
        else toast("Other changes came after that one. Use Undo at the top of the poster to step back through them.");
      },
    });
  }

  /** A narrower layer than the one being edited that sets this setting for the poster on show, if any. */
  function deeperSetter(setting) {
    const key = S.selected;
    if (!key || S.mode === "poster") return null;
    if (has(ownOf(key), setting)) return "collection";
    if (!S.editSec && has(secOwn(sectionOf(key)), setting)) return "section";
    return null;
  }

  function setAlign(value) {
    if (shown("align") === value) return;
    const updates = [["align", value]];
    // x means the left edge for left alignment and the centre for centre alignment, so move set positions
    for (const p of ["label_position", "title_position"]) {
      const pos = shown(p);
      if (Array.isArray(pos)) updates.push([p, [value === "centre" ? CENTRE_X : LEFT_X, pos[1]]]);
    }
    for (const [k, v] of updates) applySetting(k, v);
    settingsChanged();
  }

  function settingsChanged(opts) {
    const { delay = DEBOUNCE, tag = null } = opts || {};
    record(tag);
    refreshControls();
    refreshScopeUI();
    refreshPositionButtons();
    syncLists();
    syncDirty();
    schedulePreview(delay);
    gridKick();
    if (stripActive()) stripKick();
  }

  function accentStops(value, key) {
    if (Array.isArray(value)) return [value[0], value[1] || value[0]];
    if (isHex(value)) return [value, value];
    const accents = (S.info && S.info.accents) || {};
    let name = value;
    if (!value || value === "auto") {
      const c = key && S.byKey.get(key);
      name = c && c.accent;
    }
    const a = accents[name] || accents.purple || Object.values(accents)[0];
    return a ? [a.start, a.end] : ["#0a84ff", "#5e5ce6"];
  }

  function hashFor(key) {
    const c = S.byKey.get(key);
    return stable([effective(key), c ? c.artwork : null, c ? c.text || null : null, S.artRev.get(key) || 0]);
  }
  const snapshot = () => normalisePosters(S.posters);

  // ------------------------------------------------------------------ picks (which collections are on)
  function derivePicks(col) {
    const picks = new Set();
    col = col || {};
    const all = col.sections === "all";
    const secs = new Set(Array.isArray(col.sections) ? col.sections : []);
    const inc = new Set(col.include || []);
    const exc = new Set(col.exclude || []);
    for (const sec of S.sections) {
      for (const c of sec.collections) {
        if ((all || secs.has(sec.key) || inc.has(c.key)) && !exc.has(c.key)) picks.add(c.key);
      }
    }
    return picks;
  }

  /** The shortest {sections, include, exclude} for a set of picks. Unknown keys from the saved file are kept. */
  function buildCollections(picks) {
    const savedC = S.saved.collections || {};
    const known = new Set(S.order);
    const knownSecs = new Set(S.sections.map((s) => s.key));
    const keepSecs = Array.isArray(savedC.sections) ? savedC.sections.filter((s) => !knownSecs.has(s)) : [];
    const keepInc = (savedC.include || []).filter((k) => !known.has(k));
    const keepExc = (savedC.exclude || []).filter((k) => !known.has(k));
    const sections = [];
    const include = [];
    const exclude = [];
    let allIn = true;
    for (const sec of S.sections) {
      const keys = sec.collections.map((c) => c.key);
      if (!keys.length) continue;
      const picked = keys.filter((k) => picks.has(k));
      const unpicked = keys.length - picked.length;
      if (picked.length && unpicked < picked.length) {
        sections.push(sec.key);
        exclude.push(...keys.filter((k) => !picks.has(k)));
      } else {
        allIn = false;
        include.push(...picked);
      }
    }
    return {
      sections: allIn ? "all" : sections.concat(keepSecs),
      include: include.concat(keepInc),
      exclude: exclude.concat(keepExc),
    };
  }

  function setPicked(keys, on) {
    for (const k of keys) {
      if (on) S.picks.add(k);
      else S.picks.delete(k);
    }
    syncLists();
    syncDirty();
    refreshStrip();
    if (S.tab === "grid") buildGrid();
  }

  // ------------------------------------------------------------------ sizes ("Most titles"): cap, then section, then collection
  const limitRange = () => (S.info && Array.isArray(S.info.limit_range) ? S.info.limit_range.map(Number) : [1, 1000]);
  const defaultLimit = () => Number((S.info && S.info.default_limit) || 150);
  const isFranchise = (c) => c.fixed_titles !== null && c.fixed_titles !== undefined;

  function normaliseLimits(l) {
    const out = { most: null, sections: {}, collections: {} };
    const num = (v) => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v)) ? null : Math.round(Number(v)));
    if (l && num(l.most) !== null) out.most = num(l.most);
    for (const part of ["sections", "collections"]) {
      for (const [k, v] of Object.entries((l && l[part]) || {})) if (num(v) !== null) out[part][k] = num(v);
    }
    return out;
  }

  /** The size a collection gets without its own number. */
  function inheritedLimit(c) {
    if (isFranchise(c)) return null;
    if (has(S.limits.sections, c.section)) return S.limits.sections[c.section];
    const usual = Number(c.built_in_limit) || defaultLimit();
    return S.limits.most !== null ? Math.min(usual, S.limits.most) : usual;
  }
  function effLimit(c) {
    if (isFranchise(c)) return null;
    return has(S.limits.collections, c.key) ? S.limits.collections[c.key] : inheritedLimit(c);
  }
  const clampLimit = (n) => {
    const [lo, hi] = limitRange();
    return Math.min(hi, Math.max(lo, Math.round(n)));
  };

  function setCollectionLimit(key, n) {
    const c = S.byKey.get(key);
    delete S.limits.collections[key];
    if (n !== null && c) {
      n = clampLimit(n);
      if (n !== inheritedLimit(c)) S.limits.collections[key] = n;
    }
    limitsChanged();
  }
  function setSectionLimit(sec, n) {
    if (n === null) delete S.limits.sections[sec];
    else S.limits.sections[sec] = clampLimit(n);
    limitsChanged();
  }
  function setMost(n) {
    S.limits.most = n === null ? null : clampLimit(n);
    limitsChanged();
  }
  function limitsChanged() {
    syncSizes();
    syncDirty();
  }

  /** A number field that commits on change or Enter; empty means "no number of its own". */
  function numberField(label, onCommit) {
    const [lo, hi] = limitRange();
    const input = el("input", { class: "num", type: "number", min: lo, max: hi, step: 1, inputmode: "numeric", "aria-label": label });
    input.addEventListener("change", () => {
      const raw = input.value.trim();
      if (raw === "") {
        onCommit(null);
        return;
      }
      const n = Number(raw);
      if (!Number.isFinite(n)) {
        syncSizes();
        return;
      }
      onCommit(n);
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        input.blur();
      }
    });
    return input;
  }

  function syncSizes() {
    if (!S.limits) return;
    for (const [k, r] of S.ui.sizes) {
      const c = S.byKey.get(k);
      if (!c) continue;
      const n = effLimit(c);
      if (document.activeElement !== r.input) r.input.value = n === null ? "" : String(n);
      const own = has(S.limits.collections, k);
      r.input.classList.toggle("is-own", own);
      r.reset.hidden = !own;
      r.reset.title = `Back to the usual size (${inheritedLimit(c)})`;
    }
    for (const [sk, r] of S.ui.secSizes) {
      const v = has(S.limits.sections, sk) ? S.limits.sections[sk] : null;
      if (document.activeElement !== r.input) r.input.value = v === null ? "" : String(v);
      r.clear.hidden = v === null;
    }
    const on = S.limits.most !== null;
    const most = $("most-input");
    [most.min, most.max] = limitRange().map(String);
    $("most-switch").checked = on;
    $("most-field").hidden = !on;
    if (document.activeElement !== most) most.value = on ? String(S.limits.most) : "";
  }

  const matches = (c, q) => !q || c.name.toLowerCase().includes(q) || c.key.toLowerCase().includes(q);
  function matchKeys(query) {
    const q = query.trim().toLowerCase();
    return S.order.filter((k) => matches(S.byKey.get(k), q));
  }

  // ------------------------------------------------------------------ Collections tab: cards with switches
  function toggleOpen(searching, openSet, closedSet, key, isOpen) {
    if (searching) {
      if (isOpen) closedSet.add(key);
      else closedSet.delete(key);
    } else if (isOpen) openSet.delete(key);
    else openSet.add(key);
  }

  function renderCollections() {
    const box = $("col-cards");
    box.textContent = "";
    S.ui.cards = new Map();
    S.ui.ccRows = new Map();
    S.ui.sizes = new Map();
    S.ui.secSizes = new Map();
    for (const sec of S.sections) {
      const listId = "cc-list-" + sec.key;
      const countId = "cc-count-" + sec.key;
      const count = el("span", { class: "sec-card-count", id: countId });
      const toggle = el("button", { class: "sec-card-toggle", type: "button", "aria-expanded": "false", "aria-controls": listId }, [
        svg(ICON.chevron),
        el("span", { class: "sec-card-text" }, [el("span", { class: "sec-card-name", text: sec.name }), count]),
      ]);
      toggle.addEventListener("click", () => {
        toggleOpen(!!S.colSearch.trim(), S.colOpen, S.colSearchClosed, sec.key, toggle.getAttribute("aria-expanded") === "true");
        syncLists();
      });
      const sw = el("input", { class: "switch", type: "checkbox", role: "switch", "aria-label": `Every collection in ${sec.name}`, "aria-describedby": countId });
      sw.addEventListener("change", () => setPicked(sec.collections.map((c) => c.key), sw.checked));
      const design = el("button", { class: "btn btn-small sec-card-design", type: "button", "aria-label": `Design this section: ${sec.name}` }, "Design this section");
      design.addEventListener("click", () => goSection(sec.key, true));
      const ul = el("ul", { class: "sec-card-list", id: listId });
      for (const c of sec.collections) {
        const name = el("button", { class: "cc-name", type: "button", title: `Design ${c.name} (${c.key})` }, [
          el("span", { class: "cc-label", text: c.name }),
          c.streaming ? el("span", { class: "mini-tag", text: "Logo", title: "Streaming service poster" }) : null,
          el("span", { class: "cc-go", "aria-hidden": "true", text: "Design" }),
        ]);
        name.addEventListener("click", () => goPoster(c.key, true));
        const csw = el("input", { class: "switch", type: "checkbox", role: "switch", "aria-label": c.name });
        csw.addEventListener("change", () => setPicked([c.key], csw.checked));
        let size;
        if (isFranchise(c)) {
          size = el("span", { class: "size-fixed", text: `All ${c.fixed_titles} ${c.kind === "show" ? "shows" : "films"}` });
        } else {
          const input = numberField(`Most titles in ${c.name}`, (n) => setCollectionLimit(c.key, n));
          const reset = el("button", { class: "link-btn", type: "button", hidden: true, "aria-label": `Reset the size of ${c.name}` }, "reset");
          reset.addEventListener("click", () => setCollectionLimit(c.key, null));
          size = el("span", { class: "size-field" }, [el("label", { class: "size-label" }, [el("span", { text: "Up to" }), input]), reset]);
          S.ui.sizes.set(c.key, { input, reset });
        }
        const li = el("li", { class: "cc-row" }, [name, size, csw]);
        ul.append(li);
        S.ui.ccRows.set(c.key, { li, sw: csw });
      }
      if (sec.collections.some((c) => !isFranchise(c))) {
        const input = numberField(`Titles per collection in ${sec.name}`, (n) => setSectionLimit(sec.key, n));
        input.placeholder = "Usual";
        const clear = el("button", { class: "link-btn", type: "button", hidden: true, "aria-label": `Clear the size for ${sec.name}` }, "Clear to default");
        clear.addEventListener("click", () => setSectionLimit(sec.key, null));
        ul.prepend(el("li", { class: "cc-row cc-secsize" }, [
          el("label", { class: "size-label" }, [el("span", { text: "Titles per collection in this section" }), input]), clear,
        ]));
        S.ui.secSizes.set(sec.key, { input, clear });
      }
      if (!sec.collections.length) design.disabled = true;
      const card = el("article", { class: "sec-card" }, [el("div", { class: "sec-card-head" }, [toggle, design, sw]), ul]);
      box.append(card);
      S.ui.cards.set(sec.key, { card, toggle, sw, count, ul });
    }
  }

  // ------------------------------------------------------------------ Design tab: the sidebar (sections, or every poster)
  const ownDot = (title) => el("span", { class: "dot", title, hidden: true }, [el("span", { class: "vh", text: ` (${title.toLowerCase()})` })]);

  /** Whole section mode lists Every section and the sections; Each poster mode lists every collection under its section. */
  function renderDesignList() {
    const box = $("dlist");
    box.textContent = "";
    S.ui.dsecs = new Map();
    S.ui.drows = new Map();
    S.ui.dpicks = new Map();
    S.ui.dlistMode = S.mode;
    const search = $("list-search");
    const sectionMode = S.mode === "section";
    search.value = sectionMode ? S.secSearch : S.listSearch;
    search.placeholder = sectionMode ? "Find a section" : "Find a collection";
    search.setAttribute("aria-label", sectionMode ? "Find a section to design" : "Find a collection to design");
    $("dlist-nav").setAttribute("aria-label", sectionMode ? "Choose a section to design" : "Choose a poster to design");
    if (sectionMode) {
      const pick = (secKey, name, count, extraClass) => {
        const dot = ownDot(secKey ? "Has its own design settings" : "Changed from the defaults");
        const b = el("button", { class: "dl-pick" + (extraClass ? " " + extraClass : ""), type: "button" }, [
          el("span", { class: "dl-name", text: name }), dot, el("span", { class: "dl-count", text: String(count) }),
        ]);
        b.addEventListener("click", () => goSection(secKey));
        S.ui.dpicks.set(secKey || "", { btn: b, dot, name: name.toLowerCase() });
        return b;
      };
      box.append(pick(null, "Every section", S.order.length, "dl-every"), el("div", { class: "dl-divider", role: "presentation" }));
      for (const sec of S.sections) {
        if (!sec.collections.length) continue;
        box.append(pick(sec.key, sec.name, sec.collections.length));
      }
      return;
    }
    for (const sec of S.sections) {
      const listId = "dl-list-" + sec.key;
      // a plain heading: the chevron only shows or hides the section's posters
      const head = el("button", { class: "dl-head", type: "button", "aria-expanded": "true", "aria-controls": listId }, [
        svg(ICON.chevron), el("span", { class: "dl-head-name", text: sec.name }),
      ]);
      head.addEventListener("click", () => {
        const closed = S.listSearch.trim() ? S.listSearchClosed : S.listClosed;
        if (head.getAttribute("aria-expanded") === "true") closed.add(sec.key);
        else closed.delete(sec.key);
        syncLists();
      });
      const ul = el("ul", { class: "dl-list", id: listId });
      for (const c of sec.collections) {
        const cdot = ownDot("Has its own design settings");
        const off = el("span", { class: "vh", text: " (off)" });
        const b = el("button", { class: "dl-col", type: "button", title: c.key }, [el("span", { class: "dl-name", text: c.name }), off, cdot]);
        b.addEventListener("click", () => goPoster(c.key));
        const li = el("li", {}, [b]);
        ul.append(li);
        S.ui.drows.set(c.key, { li, btn: b, dot: cdot, off });
      }
      const wrap = el("div", { class: "dl-sec" }, [el("h3", { class: "dl-sec-head" }, [head]), ul]);
      box.append(wrap);
      S.ui.dsecs.set(sec.key, { wrap, head, ul });
    }
  }

  function syncDesignList() {
    if (S.ui.dlistMode !== S.mode) renderDesignList();
    if (S.mode === "section") {
      const q = S.secSearch.trim().toLowerCase();
      for (const [k, p] of S.ui.dpicks) {
        const sel = (k || null) === S.editSec;
        p.btn.classList.toggle("is-selected", sel);
        if (sel) p.btn.setAttribute("aria-current", "true");
        else p.btn.removeAttribute("aria-current");
        p.btn.hidden = !!q && !!k && !p.name.includes(q);
        p.dot.hidden = k ? !Object.keys(secOwn(k)).length : !changedGlobals().length;
      }
      $("dlist-empty").hidden = !q || [...S.ui.dpicks].some(([k, p]) => k && !p.btn.hidden);
      return;
    }
    const q = S.listSearch.trim().toLowerCase();
    let any = false;
    for (const sec of S.sections) {
      const ds = S.ui.dsecs.get(sec.key);
      if (!ds) continue;
      let vis = 0;
      for (const c of sec.collections) {
        const d = S.ui.drows.get(c.key);
        if (!d) continue;
        const m = matches(c, q);
        d.li.hidden = !m;
        if (m) vis++;
        const on = S.picks.has(c.key);
        const sel = c.key === S.selected;
        d.btn.classList.toggle("is-selected", sel);
        d.btn.classList.toggle("is-off", !on);
        d.off.hidden = on;
        if (sel) d.btn.setAttribute("aria-current", "true");
        else d.btn.removeAttribute("aria-current");
        d.dot.hidden = !Object.keys(ownOf(c.key)).length;
      }
      if (vis) any = true;
      ds.wrap.hidden = q ? vis === 0 : !sec.collections.length;
      const open = q ? !S.listSearchClosed.has(sec.key) : !S.listClosed.has(sec.key);
      ds.ul.hidden = !open;
      ds.head.setAttribute("aria-expanded", String(open));
    }
    $("dlist-empty").hidden = !q || any;
  }

  function syncLists() {
    if (!S.posters) return;
    const cq = S.colSearch.trim().toLowerCase();
    let total = 0;
    let pickedTotal = 0;
    let colMatches = 0;
    for (const sec of S.sections) {
      const card = S.ui.cards.get(sec.key);
      let picked = 0;
      let cVisible = 0;
      for (const c of sec.collections) {
        const on = S.picks.has(c.key);
        if (on) picked++;
        const row = S.ui.ccRows.get(c.key);
        if (row) {
          row.sw.checked = on;
          const m = matches(c, cq);
          row.li.hidden = !m;
          if (m) cVisible++;
        }
      }
      const n = sec.collections.length;
      total += n;
      pickedTotal += picked;
      colMatches += cVisible;
      if (card) {
        card.sw.checked = n > 0 && picked === n;
        card.sw.indeterminate = picked > 0 && picked < n;
        card.count.textContent = `${picked} of ${n} on`;
        card.card.hidden = cq ? cVisible === 0 : false;
        const open = cq ? !S.colSearchClosed.has(sec.key) : S.colOpen.has(sec.key);
        card.ul.hidden = !open;
        card.toggle.setAttribute("aria-expanded", String(open));
      }
    }
    syncDesignList();
    syncListsPanel();
    $("col-count").textContent = `${pickedTotal} of ${total} on`;
    $("all-on").textContent = cq ? "Turn matches on" : "Turn all on";
    $("all-off").textContent = cq ? "Turn matches off" : "Turn all off";
    $("col-empty").hidden = !cq || colMatches > 0;
    syncEditorPick();
  }

  // ------------------------------------------------------------------ Lists tab: where titles come from
  const listUrl = (slug) => MDBLIST + String(slug).split("/").map(encodeURIComponent).join("/");
  const fileName = () => (S.info && S.info.custom_file) || "your custom collections file";

  const kindWord = (kind, n) => (kind === "show" ? (n === 1 ? "TV show" : "TV shows") : n === 1 ? "film" : "films");
  /** The smallest collection a run makes: min_items, or the collection's own size when that's smaller. */
  const minItems = () => Number(S.info && S.info.min_items) || 8;

  /** How many of a checked list's films (or TV shows) are in the library, or null when that isn't known (demo). */
  function inLibrary(r, kind) {
    const n = r && r.in_library ? r.in_library[kind] : null;
    return n === undefined || n === null ? null : Number(n) || 0;
  }

  /** One checked list, counting what's in the library of the given kind (the Type picked, or the collection's). */
  function describeCheck(r, kind) {
    const titles = Number(r.titles) || 0;
    if (!titles) return "No titles in this list yet.";
    const movies = Number(r.movies) || 0;
    const shows = Number(r.shows) || 0;
    const most = shows > movies ? "TV shows" : "films";
    let s = `${titles} ${titles === 1 ? "title" : "titles"}, ${movies && shows ? "mostly" : "all"} ${most}.`;
    kind = kind || r.type || "movie";
    const n = inLibrary(r, kind);
    if (n !== null) s += ` ${n} of its ${kindWord(kind, 2)} ${n === 1 ? "is" : "are"} in your library.`;
    return s;
  }

  function renderListsPanel() {
    const box = $("lists-body");
    box.textContent = "";
    S.ui.lpSecs = new Map();
    S.ui.lpRows = new Map();
    for (const sec of S.sections) {
      const listId = "lp-list-" + sec.key;
      const yours = sec.collections.filter((c) => c.custom).length;
      const n = sec.collections.length;
      const count = el("span", { class: "sec-card-count", text: `${n} ${n === 1 ? "collection" : "collections"}${yours ? `, ${yours} yours` : ""}` });
      const toggle = el("button", { class: "sec-card-toggle", type: "button", "aria-expanded": "false", "aria-controls": listId }, [
        svg(ICON.chevron),
        el("span", { class: "sec-card-text" }, [el("span", { class: "sec-card-name", text: sec.name }), count]),
      ]);
      toggle.addEventListener("click", () => {
        toggleOpen(!!S.lpSearch.trim(), S.lpOpen, S.lpSearchClosed, sec.key, toggle.getAttribute("aria-expanded") === "true");
        syncListsPanel();
      });
      const ul = el("ul", { class: "sec-card-list", id: listId });
      for (const c of sec.collections) {
        const li = listRow(c);
        ul.append(li);
        S.ui.lpRows.set(c.key, { li, name: li.querySelector(".cc-name"), add: li.querySelector(".lr-add-btn") });
      }
      const card = el("article", { class: "sec-card" }, [el("div", { class: "sec-card-head" }, [toggle]), ul]);
      box.append(card);
      S.ui.lpSecs.set(sec.key, { card, toggle, ul });
    }
    syncListsPanel();
  }

  function listRow(c) {
    const name = el("button", { class: "cc-name", type: "button", title: `Design ${c.name} (${c.key})` }, [
      el("span", { class: "cc-label", text: c.name }),
      el("span", { class: "cc-go", "aria-hidden": "true", text: "Design" }),
    ]);
    name.addEventListener("click", () => goPoster(c.key, true));
    const main = el("div", { class: "lr-main" }, [name]);
    if (c.custom) {
      main.append(el("span", { class: "badge badge-yours", text: "Yours" }));
      const rm = el("button", { class: "btn btn-small btn-danger-text", type: "button", "aria-label": `Remove ${c.name}` }, "Remove");
      rm.addEventListener("click", () => removeCustom(c));
      main.append(rm);
    }
    const row = el("li", { class: "lr-row" }, [main]);
    const lists = el("div", { class: "lr-lists" });
    row.append(lists);
    if (isFranchise(c)) {
      lists.append(el("span", { class: "lr-fixed", text: `Fixed list of ${c.fixed_titles} ${c.kind === "show" ? "shows" : "films"}` }));
      return row;
    }
    const added = new Set(c.added_lists || []);
    const all = [];
    for (const s of (c.lists || []).concat(c.added_lists || [])) if (!all.includes(s)) all.push(s);
    for (const slug of all) {
      const chip = el("span", { class: "lchip" + (added.has(slug) ? " is-added" : "") }, [
        el("a", { href: listUrl(slug), target: "_blank", rel: "noopener noreferrer", title: `Open ${slug} on MDBList`, text: slug }),
      ]);
      if (c.custom || added.has(slug)) {
        const x = el("button", { class: "lchip-x", type: "button", title: "Remove this list", "aria-label": `Remove the list ${slug} from ${c.name}` }, [svg(ICON.x)]);
        x.addEventListener("click", () => removeList(c, slug));
        chip.append(x);
      }
      lists.append(chip);
    }
    const addBtn = el("button", { class: "link-btn lr-add-btn", type: "button", "aria-expanded": "false", "aria-label": `Add a list to ${c.name}` }, "+ Add a list");
    lists.append(addBtn);
    const addBox = buildAddBox(c);
    addBox.hidden = true;
    addBtn.addEventListener("click", () => {
      addBox.hidden = !addBox.hidden;
      addBtn.setAttribute("aria-expanded", String(!addBox.hidden));
      if (!addBox.hidden) addBox.querySelector("input").focus();
    });
    row.append(addBox);
    return row;
  }

  function buildAddBox(c) {
    const input = el("input", { class: "field", type: "text", placeholder: "https://mdblist.com/lists/user/list-name", "aria-label": `List to add to ${c.name}`, autocomplete: "off", spellcheck: "false" });
    const check = el("button", { class: "btn btn-small", type: "button" }, "Check");
    const add = el("button", { class: "btn btn-small btn-primary", type: "button", disabled: true }, "Add");
    const msg = el("p", { class: "lr-add-msg", role: "status" });
    let checked = null;
    input.addEventListener("input", () => {
      checked = null;
      add.disabled = true;
      msg.textContent = "";
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        (checked ? add : check).click();
      }
    });
    check.addEventListener("click", async () => {
      const text = input.value.trim();
      msg.classList.remove("is-bad");
      if (!text) {
        msg.textContent = "Paste a list address first.";
        return;
      }
      check.disabled = true;
      check.classList.add("is-busy");
      msg.textContent = "Checking the list";
      try {
        checked = await api("api/lists/check", { method: "POST", body: { list: text } });
        msg.textContent = `${checked.list}: ${describeCheck(checked, c.kind)}`;
        if (inLibrary(checked, c.kind) === 0) msg.textContent += ` Adding it adds no ${kindWord(c.kind, 2)} to ${c.name} yet.`;
        add.disabled = false;
        add.focus();
      } catch (e) {
        checked = null;
        msg.classList.add("is-bad");
        msg.textContent = e.message;
      } finally {
        check.disabled = false;
        check.classList.remove("is-busy");
      }
    });
    add.addEventListener("click", async () => {
      if (!checked) return;
      add.disabled = true;
      add.classList.add("is-busy");
      try {
        await api("api/lists/add", { method: "POST", body: { key: c.key, lists: [checked.list] } });
        toast(`Added ${checked.list} to ${c.name}. Saved to ${fileName()}; it's used on the next apply.`, "ok", 6000);
        await reloadCollections();
        focusListRow(c.key, "add");
      } catch (e) {
        msg.classList.add("is-bad");
        msg.textContent = e.message;
        add.disabled = false;
      } finally {
        add.classList.remove("is-busy");
      }
    });
    return el("div", { class: "lr-add" }, [input, check, add, msg]);
  }

  async function removeList(c, slug) {
    try {
      await api("api/lists/remove", { method: "POST", body: { key: c.key, list: slug } });
      toast(`Removed ${slug} from ${c.name}.`, "ok", 0, { label: "Undo", run: () => putListBack(c, slug) });
      await reloadCollections();
      focusListRow(c.key, "add");
    } catch (e) {
      fail(e, "List not removed");
    }
  }

  async function putListBack(c, slug) {
    try {
      await api("api/lists/add", { method: "POST", body: { key: c.key, lists: [slug] } });
      toast(`${slug} is back in ${c.name}.`, "ok");
      await reloadCollections();
    } catch (e) {
      fail(e, "List not put back");
    }
  }

  /** After the Lists tab is drawn again: focus the row's "Add a list" (or its name), or the search if it's gone. */
  function focusListRow(key, what) {
    const r = key && S.ui.lpRows.get(key);
    const target = r && ((what === "add" && r.add) || r.name);
    if (S.tab !== "lists") return;
    if (target && !target.closest("[hidden]")) target.focus();
    else $("lists-search").focus();
  }

  async function removeCustom(c) {
    const ok = await confirmDialog({
      title: `Remove ${c.name}?`,
      text: `This takes it out of ${fileName()} straight away. If it was already made on your server, it stays there until you remove it on the server.`,
      ok: "Remove",
      danger: true,
    });
    if (!ok) return;
    // focus goes to the next collection in its section afterwards, or the one before
    const keys = (S.secByKey.get(c.section) || { collections: [] }).collections.map((x) => x.key);
    const at = keys.indexOf(c.key);
    const next = keys[at + 1] || keys[at - 1] || null;
    try {
      const res = await api("api/lists/remove", { method: "POST", body: { key: c.key } });
      toast(res.message || `Removed ${c.name}.`, "ok", 9000);
      await reloadCollections();
      focusListRow(next);
    } catch (e) {
      fail(e, "Not removed");
    }
  }

  function syncListsPanel() {
    if (!S.ui.lpSecs.size) return;
    const q = S.lpSearch.trim().toLowerCase();
    let shown = 0;
    for (const sec of S.sections) {
      const ui = S.ui.lpSecs.get(sec.key);
      if (!ui) continue;
      let vis = 0;
      for (const c of sec.collections) {
        const r = S.ui.lpRows.get(c.key);
        if (!r) continue;
        const m = matches(c, q);
        r.li.hidden = !m;
        if (m) vis++;
      }
      shown += vis;
      ui.card.hidden = q ? vis === 0 : false;
      const open = q ? !S.lpSearchClosed.has(sec.key) : S.lpOpen.has(sec.key);
      ui.ul.hidden = !open;
      ui.toggle.setAttribute("aria-expanded", String(open));
    }
    $("lists-empty").hidden = !q || shown > 0;
  }

  // ---- new collection from MDBList
  function ncRow() {
    const box = $("nc-lists");
    const input = el("input", { class: "field nc-input", type: "text", placeholder: "https://mdblist.com/lists/user/list-name", "aria-label": "MDBList list address", autocomplete: "off", spellcheck: "false" });
    input.addEventListener("input", ncListsChanged);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        ncCheck();
      }
    });
    const row = el("div", { class: "nc-row" }, [input]);
    if (box.children.length) {
      const x = el("button", { class: "btn btn-icon btn-small", type: "button", "aria-label": "Remove this list" }, [svg(ICON.x)]);
      x.addEventListener("click", () => {
        const before = row.previousElementSibling;
        row.remove();
        ncListsChanged();
        syncNcAdd();
        if (before) before.querySelector("input").focus();  // not lost with the row
      });
      row.append(x);
    }
    box.append(row);
    syncNcAdd();
    return input;
  }
  function syncNcAdd() {
    $("nc-add-list").disabled = $("nc-lists").children.length >= MAX_NEW_LISTS;
  }
  function ncListsChanged() {
    if (!S.nc.checked) return;
    S.nc.checked = null;
    showNcResult([el("p", { text: "The lists changed. Check them again before you use them." })]);
    $("nc-create").disabled = true;
    $("nc-ex-add").disabled = true;
    syncNcWarn();
  }

  const ncType = () => (document.querySelector('input[name="nc-type"]:checked') || {}).value || "movie";

  /** The checked lists, counting what's in the library as the Type picked (or the chosen collection's type). */
  function showNcChecked() {
    const results = S.nc.checked || [];
    const kind = ncMode() === "existing" ? (S.byKey.get($("nc-ex-select").value) || {}).kind || ncType() : ncType();
    showNcResult(results.map((r) => el("div", { class: "nc-check-line" }, [
      el("a", { href: r.url || listUrl(r.list), target: "_blank", rel: "noopener noreferrer", text: r.list }),
      `: ${describeCheck(r, kind)}`,
      r.sample && r.sample.length ? el("div", { class: "nc-sample" }, r.sample.slice(0, 6).map((s) => el("span", { class: "pill", text: s }))) : null,
    ])));
    syncNcWarn();
  }

  /**
   * Under the check: how many of the lists' titles of the picked type are in the library, against the smallest
   * collection a run makes. Create is turned off when none are, since the collection would be empty.
   */
  function syncNcWarn() {
    const warn = $("nc-warn");
    const results = S.nc.checked;
    warn.hidden = true;
    warn.classList.remove("is-bad");
    if (!results || !results.length || $("nc-mode").hidden) return;
    const existing = ncMode() === "existing";
    const target = existing ? S.byKey.get($("nc-ex-select").value) : null;
    const kind = existing ? (target ? target.kind : null) : ncType();
    const counts = kind ? results.map((r) => inLibrary(r, kind)) : [];
    const known = counts.length > 0 && counts.every((n) => n !== null);
    $("nc-create").disabled = false;
    if (!known) return;  // demo mode, or no collection picked yet
    const n = counts.reduce((a, b) => a + b, 0);
    const several = results.length > 1;
    const what = kindWord(kind, 2);
    const other = kind === "show" ? "movie" : "show";
    const others = results.reduce((a, r) => a + (inLibrary(r, other) || 0), 0);
    let text = "";
    let bad = false;
    if (existing) {
      if (n === 0) text = `None of ${several ? "these lists'" : "this list's"} ${what} are in your library, so ${target.name} gets nothing new from ${several ? "them" : "it"} yet.`;
    } else if (n === 0) {
      text = `None of ${several ? "these lists'" : "this list's"} ${what} are in your library, so the collection would be empty.`
        + (others ? ` ${others} ${others === 1 ? "is" : "are"} there as ${kindWord(other, 2)}: pick ${kindWord(other, 2)} above.` : "");
      $("nc-create").disabled = true;
      bad = true;
    } else {
      const size = Math.round(Number($("nc-limit").value));
      const need = Math.min(minItems(), Number.isFinite(size) && size > 0 ? size : minItems());
      if (n < need) {
        text = `${several ? "At most " : "Only "}${n} ${kindWord(kind, n)} ${n === 1 ? "is" : "are"} in your library. A run skips `
          + `collections with fewer than ${need} titles, so this one isn't made until more of ${several ? "them" : "it"} are there.`;
        bad = true;
      } else if (several) {
        text = `Together, up to ${n} ${what} are in your library (a title on two lists is counted twice here).`;
      }
    }
    warn.textContent = text;
    warn.hidden = !text;
    warn.classList.toggle("is-bad", bad);
  }
  function showNcResult(children) {
    const r = $("nc-result");
    r.textContent = "";
    r.append(...children);
    r.hidden = false;
  }
  function setNcError(msg) {
    $("nc-error").hidden = !msg;
    $("nc-error").textContent = msg;
  }
  function titleFromSlug(slug) {
    const s = String(slug || "").split("/").pop() || "";
    return s.replace(/[-_]+/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase()).trim().slice(0, 60);
  }

  async function ncCheck() {
    const inputs = [...document.querySelectorAll("#nc-lists .nc-input")];
    const texts = inputs.map((i) => i.value.trim()).filter(Boolean);
    if (!texts.length) {
      showNcResult([el("p", { text: "Paste at least one list address." })]);
      inputs[0].focus();
      return;
    }
    const btn = $("nc-check");
    btn.disabled = true;
    btn.classList.add("is-busy");
    $("nc-done").hidden = true;
    const results = [];
    try {
      for (const t of texts) {
        try {
          results.push(await api("api/lists/check", { method: "POST", body: { list: t } }));
        } catch (e) {
          if (e.status === 401) return;
          S.nc.checked = null;
          $("nc-create").disabled = true;
          syncNcWarn();
          showNcResult([el("p", { class: "signin-error", text: `${t}: ${e.message}` })]);
          return;
        }
      }
    } finally {
      btn.disabled = false;
      btn.classList.remove("is-busy");
    }
    S.nc.checked = results;
    const movies = results.reduce((n, r) => n + (Number(r.movies) || 0), 0);
    const shows = results.reduce((n, r) => n + (Number(r.shows) || 0), 0);
    const type = shows > movies ? "show" : movies > shows ? "movie" : results[0].type || "movie";
    if (!S.nc.typeTouched) for (const r of document.querySelectorAll('input[name="nc-type"]')) r.checked = r.value === type;
    if (!$("nc-title").value.trim()) $("nc-title").value = titleFromSlug(results[0].list);
    $("nc-create").disabled = false;
    $("nc-ex-add").disabled = false;
    setNcError("");
    setExError("");
    fillExisting();
    $("nc-mode").hidden = false;
    syncNcMode();
  }

  const ncMode = () => (document.querySelector('input[name="nc-mode"]:checked') || {}).value || "new";
  function syncNcMode() {
    const shown = !$("nc-mode").hidden;
    $("nc-form").hidden = !shown || ncMode() !== "new";
    $("nc-existing").hidden = !shown || ncMode() !== "existing";
    if (shown && S.nc.checked) showNcChecked();
    else syncNcWarn();
  }
  function setExError(msg) {
    $("nc-ex-error").hidden = !msg;
    $("nc-ex-error").textContent = msg;
  }

  /** The picker of list-based collections (franchises have fixed titles, so they can't take a list). */
  function fillExisting() {
    const sel = $("nc-ex-select");
    const keep = sel.value;
    const q = $("nc-ex-search").value.trim().toLowerCase();
    sel.textContent = "";
    for (const sec of S.sections) {
      const opts = sec.collections.filter((c) => !isFranchise(c) && matches(c, q))
        .map((c) => el("option", { value: c.key, text: c.custom ? `${c.name} (yours)` : c.name }));
      if (opts.length) sel.append(el("optgroup", { label: sec.name }, opts));
    }
    if (keep && [...sel.options].some((o) => o.value === keep)) sel.value = keep;
  }

  async function ncAddExisting() {
    if (!S.nc.checked || !S.nc.checked.length) {
      setExError("Check the lists first.");
      return;
    }
    const key = $("nc-ex-select").value;
    const c = S.byKey.get(key);
    if (!c) {
      setExError("Pick a collection to add the lists to.");
      $("nc-ex-select").focus();
      return;
    }
    const lists = [...new Set(S.nc.checked.map((r) => r.list))];
    const btn = $("nc-ex-add");
    btn.disabled = true;
    btn.classList.add("is-busy");
    setExError("");
    try {
      await api("api/lists/add", { method: "POST", body: { key, lists } });
      await reloadCollections();
      showNcDone(`Added ${listText(lists)} to ${c.name}. Saved to ${fileName()}; it's used on the next apply.`, key, "Add another");
    } catch (e) {
      setExError(e.message);
    } finally {
      btn.classList.remove("is-busy");
      btn.disabled = false;
    }
  }

  /** After a create or an add: say what happened, offer another (keeping section, accent, type and size) and Design it. */
  function showNcDone(text, key, againLabel) {
    S.nc.checked = null;
    $("nc-mode").hidden = true;
    $("nc-result").hidden = true;
    syncNcMode();
    const again = el("button", { class: "btn btn-small", type: "button" }, againLabel);
    again.addEventListener("click", ncNext);
    const design = el("button", { class: "btn btn-small btn-primary", type: "button" }, "Design it");
    design.addEventListener("click", () => goPoster(key, true));
    const done = $("nc-done");
    done.textContent = "";
    done.append(el("span", { text }), again, design);
    done.hidden = false;
    design.focus();  // the button pressed has gone with the form
  }

  function ncNext() {
    $("nc-done").hidden = true;
    $("nc-lists").textContent = "";
    const first = ncRow();
    for (const id of ["nc-title", "nc-title2", "nc-subtitle"]) $(id).value = "";
    $("nc-twolines").checked = false;
    $("nc-title2").hidden = true;
    setNcError("");
    setExError("");
    first.focus();
  }

  function renderNewCollection() {
    $("nc-lists").textContent = "";
    ncRow();
    const box = $("nc-accent");
    box.textContent = "";
    const accents = Object.entries(S.info.accents || {});
    S.nc.accent = accents.length ? accents[0][0] : "#0a84ff";
    const color = el("input", { type: "color", "aria-label": "Custom accent colour", value: "#ffffff" });
    const custom = el("span", { class: "chip chip-custom" }, [el("label", { class: "chip-face", title: "Custom accent colour" }, [color, el("span", { text: "Custom" })])]);
    for (const [n, a] of accents) {
      const input = el("input", { class: "vh", type: "radio", name: "nc-accent", value: n, "aria-label": cap(n) });
      input.checked = n === S.nc.accent;
      input.addEventListener("change", () => {
        if (!input.checked) return;
        S.nc.accent = n;
        custom.classList.remove("is-on");
      });
      const face = el("span", { class: "chip-face chip-grad", title: cap(n) });
      face.style.setProperty("--c1", a.start);
      face.style.setProperty("--c2", a.end);
      box.append(el("label", { class: "chip" }, [input, face]));
    }
    const pickCustom = () => {
      S.nc.accent = color.value.toLowerCase();
      custom.classList.add("is-on");
      for (const r of box.querySelectorAll('input[type="radio"]')) r.checked = false;
    };
    for (const ev of ["input", "change", "click"]) color.addEventListener(ev, pickCustom);
    box.append(custom);
    $("nc-limit").value = String(Math.min(500, defaultLimit()));
  }

  function fillNcSections() {
    const sel = $("nc-section");
    const keep = sel.value;
    sel.textContent = "";
    for (const sec of S.sections) sel.append(el("option", { value: sec.key, text: sec.name }));
    sel.append(el("option", { value: "__new", text: "New section..." }));
    if (keep && [...sel.options].some((o) => o.value === keep)) sel.value = keep;
    $("nc-section-name").hidden = sel.value !== "__new";
  }

  async function ncCreate(e) {
    e.preventDefault();
    if (!S.nc.checked || !S.nc.checked.length) {
      setNcError("Check the lists first.");
      return;
    }
    const l1 = $("nc-title").value.trim();
    const l2 = $("nc-twolines").checked ? $("nc-title2").value.trim() : "";
    if (!l1) {
      setNcError("Give the collection a title.");
      $("nc-title").focus();
      return;
    }
    if ((l1 + l2).length > 60) {
      setNcError("The title can be up to 60 characters.");
      return;
    }
    const limit = Math.round(Number($("nc-limit").value));
    if (!Number.isFinite(limit) || limit < 1 || limit > 500) {
      setNcError("Most titles must be a number from 1 to 500.");
      $("nc-limit").focus();
      return;
    }
    const collection = {
      title: l2 ? `${l1}\n${l2}` : l1,
      type: (document.querySelector('input[name="nc-type"]:checked') || {}).value || "movie",
      accent: S.nc.accent,
      lists: [...new Set(S.nc.checked.map((r) => r.list))],
      limit,
    };
    const subtitle = $("nc-subtitle").value.trim();
    if (subtitle) collection.subtitle = subtitle;
    if ($("nc-section").value === "__new") {
      const nm = $("nc-section-name").value.trim();
      if (!nm) {
        setNcError("Name the new section.");
        $("nc-section-name").focus();
        return;
      }
      collection.section_name = nm;
    } else {
      collection.section = $("nc-section").value;
    }
    const btn = $("nc-create");
    btn.disabled = true;
    btn.classList.add("is-busy");
    setNcError("");
    try {
      const res = await api("api/lists/add", { method: "POST", body: { collection } });
      await reloadCollections(res.key);
      const c = S.byKey.get(res.key);
      showNcDone(
        `Created ${c ? c.name : collection.title.replace("\n", " ")}. Saved to ${fileName()}. It's made on the next apply. `
          + (S.saved.picks.has(res.key) ? "It's already on in your saved picks." : "It's turned on in your picks; press Save to keep that."),
        res.key, "Create another",
      );
    } catch (err) {
      setNcError(err.message);
    } finally {
      btn.classList.remove("is-busy");
      btn.disabled = false;
    }
  }

  /** Re-read the collections after a list change, keeping unsaved designs, picks and sizes. */
  async function reloadCollections(newKey) {
    let cols;
    try {
      cols = await api("api/collections");
    } catch (e) {
      fail(e, "Couldn't reload the collections");
      return;
    }
    const oldKeys = new Set(S.order);
    const keep = new Set(S.picks);
    setupData(cols);
    S.saved.picks = derivePicks(S.saved.collections);
    S.picks = new Set([...keep].filter((k) => S.byKey.has(k)));
    for (const k of S.order) if (!oldKeys.has(k) && S.saved.picks.has(k)) S.picks.add(k);
    if (newKey && S.byKey.has(newKey)) S.picks.add(newKey);
    S.strip.sec = null;
    S.strip.keys = [];
    renderCollections();
    renderDesignList();
    renderListsPanel();
    fillNcSections();
    if (S.editSec && !S.secByKey.has(S.editSec)) S.editSec = null;
    if (S.posterKey && !S.byKey.has(S.posterKey)) S.posterKey = null;
    if (!S.selected || !S.byKey.has(S.selected)) {
      S.selected = null;
      restoreMode();
    } else {
      renderEditorHead();
      refreshTextCard();
    }
    syncLists();
    syncSizes();
    syncDirty();
    refreshScopeUI();
    fillExisting();
    schedulePreview(0);
    if (S.tab === "grid") buildGrid();
  }

  // ------------------------------------------------------------------ style controls (right)
  function controlRow(setting, label, hint) {
    const labelId = "lbl-" + setting;
    const mark = el("span", { class: "ctl-set", hidden: true }, "Set here");
    const reset = el("button", { class: "link-btn", type: "button", hidden: true, "aria-label": `Reset the ${SETTING_NAMES[setting] || setting}` }, "reset");
    reset.addEventListener("click", () => inherit(setting));
    const head = el("div", { class: "ctl-head" }, [el("span", { class: "ctl-label", id: labelId, text: label }), mark, reset]);
    const body = el("div", { class: "ctl-body" });
    const row = el("div", { class: "ctl", "data-setting": setting }, [head, body, hint ? el("p", { class: "ctl-hint", text: hint }) : null]);
    return { row, head, body, mark, reset, labelId };
  }

  function register(setting, r, set, disable) {
    S.ui.controls[setting] = { row: r.row, mark: r.mark, reset: r.reset, set, disable: disable || (() => {}) };
  }

  function onControl(setting, value) {
    if (setting === "align") setAlign(value);
    else setSetting(setting, value);
  }

  function segControl(setting, label, values, hint, names = LABELS[setting] || {}) {
    const r = controlRow(setting, label, hint);
    const seg = el("div", { class: "seg", role: "radiogroup", "aria-labelledby": r.labelId });
    const inputs = values.map((v) => {
      const input = el("input", { class: "vh", type: "radio", name: "ctl-" + setting, value: v });
      input.addEventListener("change", () => { if (input.checked) onControl(setting, v); });
      seg.append(el("label", { class: "seg-opt" }, [input, el("span", { text: names[v] || cap(v) })]));
      return input;
    });
    r.body.append(seg);
    register(setting, r,
      (v) => { for (const i of inputs) i.checked = i.value === v; },
      (dis) => { for (const i of inputs) i.disabled = dis; });
    return r.row;
  }

  /** An iOS switch for an on/off setting. `toValue` maps checked to the stored value. */
  function switchControl(setting, label, isOn, toValue, hint) {
    const r = controlRow(setting, label, hint);
    r.row.classList.add("ctl-switch");
    const sw = el("input", { class: "switch", type: "checkbox", role: "switch", "aria-labelledby": r.labelId });
    sw.addEventListener("change", () => setSetting(setting, toValue(sw.checked)));
    r.head.append(sw);
    register(setting, r, (v) => { sw.checked = isOn(v); }, (dis) => { sw.disabled = dis; });
    return r.row;
  }

  function customColour(setting, label, container, start) {
    const input = el("input", { type: "color", "aria-label": label, value: start || "#ffffff" });
    const chip = el("span", { class: "chip chip-custom" }, [
      el("label", { class: "chip-face", title: label }, [input, el("span", { text: "Custom" })]),
    ]);
    input.addEventListener("input", () => setSetting(setting, input.value));
    input.addEventListener("change", () => setSetting(setting, input.value));
    // choosing the custom chip applies its colour straight away, before the picker changes it
    input.addEventListener("click", () => {
      if (shown(setting) !== input.value.toLowerCase()) setSetting(setting, input.value);
    });
    container.append(chip);
    return {
      input,
      set(hex) {
        chip.classList.toggle("is-on", !!hex);
        if (hex && input.value.toLowerCase() !== hex.toLowerCase()) input.value = hex;
      },
    };
  }

  function accentControl() {
    const r = controlRow("accent", "Accent colour", "Auto uses each collection's own colour.");
    const chips = el("div", { class: "chips", role: "radiogroup", "aria-labelledby": r.labelId });
    const radios = [];
    const chip = (value, faceClass, content, title) => {
      const input = el("input", { class: "vh", type: "radio", name: "ctl-accent", value, "aria-label": title });
      input.addEventListener("change", () => { if (input.checked && value !== "__pair") setSetting("accent", value); });
      const face = el("span", { class: "chip-face " + faceClass, title }, content);
      const wrap = el("label", { class: "chip" + (value === "auto" ? " chip-auto" : "") }, [input, face]);
      chips.append(wrap);
      radios.push(input);
      return { input, face, wrap };
    };
    const autoDot = el("span", { class: "dot-grad" });
    chip("auto", "", [autoDot, el("span", { text: "Auto" })], "Auto: each collection's own colour");
    for (const [name, a] of Object.entries(S.info.accents || {})) {
      const c = chip(name, "chip-grad", [], cap(name));
      c.face.style.setProperty("--c1", a.start);
      c.face.style.setProperty("--c2", a.end);
    }
    const pair = chip("__pair", "chip-grad", [], "Custom colour pair from your config");
    pair.wrap.hidden = true;
    const first = Object.values(S.info.accents || {})[0];
    const custom = customColour("accent", "Custom accent colour", chips, first ? first.start : "#ffffff");
    r.body.append(chips);
    register("accent", r, (v) => {
      const stops = accentStops("auto", S.selected);
      autoDot.style.setProperty("--c1", stops[0]);
      autoDot.style.setProperty("--c2", stops[1]);
      const isPair = Array.isArray(v);
      pair.wrap.hidden = !isPair;
      if (isPair) {
        pair.face.style.setProperty("--c1", v[0]);
        pair.face.style.setProperty("--c2", v[1] || v[0]);
      }
      for (const i of radios) i.checked = isPair ? i.value === "__pair" : i.value === v;
      custom.set(isHex(v) ? v : null);
    }, (dis) => {
      for (const i of radios) i.disabled = dis;
      custom.input.disabled = dis;
    });
    return r.row;
  }

  function colourControl(setting, label) {
    const r = controlRow(setting, label);
    const chips = el("div", { class: "chips", role: "radiogroup", "aria-labelledby": r.labelId });
    const radios = [];
    let accentSwatch = null;
    for (const v of S.info.text_colours || ["gold", "white", "accent"]) {
      const sw = el("span", { class: "swatch" });
      if (v === "gold" && S.info.gold) sw.style.setProperty("--c1", S.info.gold);
      else if (v === "white") sw.style.setProperty("--c1", "#ffffff");
      else if (v === "accent") accentSwatch = sw;
      else if (isHex(v)) sw.style.setProperty("--c1", v);
      const input = el("input", { class: "vh", type: "radio", name: "ctl-" + setting, value: v });
      input.addEventListener("change", () => { if (input.checked) setSetting(setting, v); });
      chips.append(el("label", { class: "chip" }, [input, el("span", { class: "chip-face" }, [sw, el("span", { text: LABELS.text[v] || cap(v) })])]));
      radios.push(input);
    }
    const custom = customColour(setting, `Custom ${label.toLowerCase()}`, chips, "#ffffff");
    r.body.append(chips);
    register(setting, r, (v, vals) => {
      if (accentSwatch) accentSwatch.style.setProperty("--c1", accentStops(vals.accent, S.selected)[0]);
      for (const i of radios) i.checked = i.value === v;
      custom.set(isHex(v) ? v : null);
    }, (dis) => {
      for (const i of radios) i.disabled = dis;
      custom.input.disabled = dis;
    });
    return r.row;
  }

  /** The font for all the text: a wrapping row of font names, which the server sends with their keys. */
  function fontControl(values) {
    const hint = "For the label, title and subtitle. Text with a letter the font doesn't have is drawn in Poppins.";
    const row = segControl("font", "Font", values, hint, (S.info && S.info.fonts) || {});
    row.querySelector(".seg").classList.add("seg-wrap");
    return row;
  }

  function sizeLimits(setting) {
    const lim = S.info && S.info.limits && S.info.limits[setting];
    return Array.isArray(lim) && lim.length === 2 ? lim.map(Number) : [0.5, 2.0];
  }

  function sizeControl(setting, label, hint) {
    const lim = sizeLimits(setting);
    const r = controlRow(setting, label, hint);
    const out = el("span", { class: "ctl-value", "aria-hidden": "true" });
    r.head.append(out);
    const input = el("input", { class: "range", type: "range", min: lim[0], max: lim[1], step: SIZE_STEP, "aria-labelledby": r.labelId });
    input.addEventListener("input", () => setSetting(setting, Number(input.value)));
    r.body.append(input);
    register(setting, r, (v) => {
      const n = Number(v) || 1;
      if (Math.abs(Number(input.value) - n) > 0.001) input.value = String(n);
      const pct = Math.round(n * 100) + "%";
      out.textContent = pct;
      input.setAttribute("aria-valuetext", pct);
    }, (dis) => { input.disabled = dis; });
    return r.row;
  }

  function renderControls() {
    const body = $("controls-body");
    body.textContent = "";
    S.ui.controls = {};
    const ch = S.info.choices || {};
    const group = (title, rows) => {
      const kept = rows.filter(Boolean);
      if (kept.length) body.append(el("div", { class: "ctl-group" }, [el("h3", { text: title }), ...kept]));
    };
    // case is on/off when it is just normal or upper: a Capitals switch, otherwise a segmented control
    const caseValues = ch.case || [];
    const caseSwitch = caseValues.length === 2 && caseValues.includes("upper");
    const caseOff = caseValues.find((v) => v !== "upper") || "normal";
    group("Colour", [accentControl()]);
    group("Background", [
      ch.shade && segControl("shade", "Shade", ch.shade, "How much the artwork is darkened."),
      ch.tint && segControl("tint", "Tint", ch.tint, "How strongly the accent colour washes over the artwork."),
    ]);
    group("Text", [
      ch.font && fontControl(ch.font),
      ch.title && segControl("title", "Title style", ch.title),
      sizeControl("title_size", "Title size", "The title and subtitle together. Long titles still shrink to fit."),
      ch.align && segControl("align", "Alignment", ch.align, "Applies to the label and the title."),
      caseSwitch
        ? switchControl("case", "Capitals", (v) => v === "upper", (on) => (on ? "upper" : caseOff))
        : caseValues.length && segControl("case", "Case", caseValues),
      ch.text_shadow && segControl("text_shadow", "Text shadow", ch.text_shadow, "Auto adds a soft shadow only to text you've moved."),
    ]);
    group("Label and subtitle", [
      switchControl("label", "Show the label", (v) => !!v, (on) => on),
      sizeControl("label_size", "Label size"),
      colourControl("label_colour", "Label colour"),
      colourControl("subtitle_colour", "Subtitle colour"),
    ]);
    if (ch.artwork) {
      group("Artwork", [
        segControl("artwork", "Artwork", ch.artwork,
          "Fixed uses the same title's artwork everywhere. Random picks one of the top titles for this server and keeps it. "
          + "Mosaic lays out a grid of the collection's own posters. Streaming posters keep their own look."),
        ch.mosaic && segControl("mosaic", "Mosaic grid", ch.mosaic,
          "A collection with too few titles that have posters gets one artwork instead."),
      ]);
    }
  }

  function refreshControls() {
    if (!S.posters || !S.ui.controls) return;
    const vals = scopeValues();
    const own = ownAtScope();
    const changed = own ? null : new Set(changedGlobals());
    for (const [setting, c] of Object.entries(S.ui.controls)) {
      c.set(shown(setting), vals);
      const isSet = !!own && has(own, setting);
      c.mark.hidden = !isSet;
      c.reset.hidden = own ? !isSet : !changed.has(setting);
      // the grid size only matters where the artwork is a mosaic
      if (setting === "mosaic") c.row.hidden = vals.artwork !== "mosaic";
      const dis = (setting === "label_colour" || setting === "label_size") && !shown("label");
      c.disable(dis);
      c.row.classList.toggle("is-disabled", dis);
    }
    for (const g of $("controls-body").querySelectorAll(".ctl-group")) {
      g.hidden = ![...g.querySelectorAll(".ctl")].some((r) => !r.hidden);
    }
  }

  // ---- logo card: the version of a streaming service's logo and its colours
  /** What the logo card shows: generic choices for a section or every poster, one service's versions for one poster. */
  function logoContext() {
    const c = S.byKey.get(S.selected);
    if (S.mode === "poster") return c && c.streaming ? { kind: "service", service: c.service || "", id: "svc:" + (c.service || "") } : null;
    if (!S.editSec) return { kind: "every", id: "every" };
    const sec = S.secByKey.get(S.editSec);
    return sec && sec.collections.some((x) => x.streaming) ? { kind: "section", id: "section" } : null;
  }

  function logoVersions(service) {
    const v = S.info && S.info.logo_versions && S.info.logo_versions[service];
    return Array.isArray(v) && v.length ? v : [{ key: "standard", label: "Standard", downloaded: false }];
  }

  function refreshLogoCard() {
    const ctx = logoContext();
    const panel = $("logo-panel");
    panel.hidden = !ctx;
    if (!ctx) {
      delete S.ui.controls.logo;
      delete S.ui.controls.logo_colour;
      S.ui.logoCtx = null;
      return;
    }
    $("logo-heading").textContent = ctx.kind === "every" ? "Streaming posters" : "Logo";
    if (S.ui.logoCtx === ctx.id && S.ui.controls.logo) return;
    S.ui.logoCtx = ctx.id;
    const body = $("logo-body");
    body.textContent = "";
    const ch = (S.info && S.info.choices) || {};
    let versions;
    if (ctx.kind === "service") versions = logoVersions(ctx.service);
    else versions = (ch.logo || ["standard", "alt", "icon"]).map((k) => ({ key: k, label: LABELS.logo[k] || cap(k), downloaded: true }));
    const r = controlRow("logo", "Logo", ctx.kind === "service" ? LOGO_MISSING : LOGO_HINT);
    const hint = r.row.querySelector(".ctl-hint");
    const seg = el("div", { class: "seg seg-wrap", role: "radiogroup", "aria-labelledby": r.labelId });
    const inputs = versions.map((v) => {
      const input = el("input", { class: "vh", type: "radio", name: "ctl-logo", value: v.key });
      input.addEventListener("change", () => { if (input.checked) setSetting("logo", v.key); });
      seg.append(el("label", { class: "seg-opt", title: v.downloaded ? null : "Not downloaded yet" }, [input, el("span", { text: v.label })]));
      return input;
    });
    r.body.append(seg);
    register("logo", r, (val) => {
      // a version this service doesn't have falls back to its standard logo, as the poster does
      const pick = versions.some((v) => v.key === val) ? val : "standard";
      for (const i of inputs) i.checked = i.value === pick;
      if (ctx.kind === "service") {
        const ver = versions.find((v) => v.key === pick);
        hint.hidden = !!ver && ver.downloaded;
      }
    }, (dis) => { for (const i of inputs) i.disabled = dis; });
    body.append(r.row, segControl("logo_colour", "Logo colours", ch.logo_colour || ["original", "white"]));
    refreshControls();
  }

  const allStreaming = (sec) => !!sec && sec.collections.length > 0 && sec.collections.every((x) => x.streaming);

  /** One line saying exactly what is being edited. */
  function bannerText() {
    if (S.mode === "poster") {
      const c = S.byKey.get(S.selected);
      return c ? `You're editing only ${c.name}.` : "";
    }
    if (!S.editSec) return "You're editing every poster. Sections and posters with their own settings keep them.";
    const sec = S.secByKey.get(S.editSec);
    if (!sec) return "";
    const n = sec.collections.length;
    const what = allStreaming(sec) ? "the text and logo" : "the text and the poster artwork, colour, shade and tint";
    return n === 1 ? `You're editing the whole ${sec.name} section: ${what} of its only poster.`
      : `You're editing the whole ${sec.name} section: ${what} of all ${n} posters.`;
  }

  function refreshScopeUI() {
    if (!S.posters) return;
    const key = S.selected;
    const c = key && S.byKey.get(key);
    const sec = c && S.secByKey.get(c.section);
    for (const r of document.querySelectorAll('input[name="mode"]')) r.checked = r.value === S.mode;
    const line = bannerText();
    const sl = $("scope-line");
    if (sl.textContent !== line) sl.textContent = line;
    $("mode-banner").classList.toggle("is-poster", S.mode === "poster");
    let short = "Every section";
    if (S.mode === "poster" && c) short = `Only ${c.name}`;
    else if (S.editSec) short = `Whole section: ${(S.secByKey.get(S.editSec) || {}).name || ""}`;
    const cs = $("controls-scope");
    cs.textContent = short;
    cs.title = short;
    $("stream-sec-note").hidden = !(S.mode === "section" && allStreaming(S.secByKey.get(S.editSec)));
    // say when narrower settings win over edits here, for the poster on show
    const deeper = [];
    let count = 0;
    const names = (obj) => {
      count += Object.keys(obj).length;
      return listText(Object.keys(obj).map((k) => SETTING_NAMES[k] || k.replace(/_/g, " ")));
    };
    if (c && S.mode === "section") {
      if (!S.editSec && Object.keys(secOwn(c.section)).length) deeper.push(`${sec.name} has its own ${names(secOwn(c.section))}.`);
      if (Object.keys(ownOf(key)).length) deeper.push(`${c.name} has its own ${names(ownOf(key))}.`);
    }
    const dn = $("deeper-note");
    dn.hidden = !deeper.length;
    dn.textContent = deeper.length ? `${deeper.join(" ")} ${count > 1 ? "Those win" : "That wins"} over changes here.` : "";
    const own = ownAtScope();
    const btn = $("scope-reset");
    btn.hidden = own ? !Object.keys(own).length : !changedGlobals().length;
    btn.textContent = S.mode === "poster" ? "Reset this poster" : S.editSec ? "Reset this section" : "Reset to the defaults";
    refreshLogoCard();
    refreshStreamUI();
    refreshStrip();
  }

  /** The poster to show for a section: its first collection that is on. For every poster, the first one on that isn't a streaming poster. */
  function stageKeyFor(secKey) {
    if (secKey) {
      const sec = S.secByKey.get(secKey);
      if (!sec || !sec.collections.length) return null;
      return (sec.collections.find((x) => S.picks.has(x.key)) || sec.collections[0]).key;
    }
    const isStream = (k) => !!S.byKey.get(k).streaming;
    return S.order.find((k) => S.picks.has(k) && !isStream(k)) || S.order.find((k) => !isStream(k)) || S.order[0] || null;
  }

  /** Whole section mode on a section, or on every poster when secKey is null. */
  function openSection(secKey) {
    secKey = secKey || null;
    if (secKey && !(S.secByKey.get(secKey) || { collections: [] }).collections.length) return;
    const stay = S.mode === "section" && S.editSec === secKey && !!S.selected && (!secKey || sectionOf(S.selected) === secKey);
    S.mode = "section";
    S.editSec = secKey;
    closeChooser();
    const key = stay ? S.selected : stageKeyFor(secKey);
    syncDesignList();
    if (key) selectCollection(key);
    else refreshScopeUI();
    announce(bannerText());
  }

  /** Each poster mode on one collection. */
  function openPoster(key) {
    if (!S.byKey.has(key)) return;
    S.mode = "poster";
    S.posterKey = key;
    S.listClosed.delete(sectionOf(key));
    S.listSearchClosed.delete(sectionOf(key));
    syncDesignList();
    selectCollection(key);
  }

  /** The mode switch: each mode comes back to what it was editing last. */
  async function setMode(mode) {
    if (mode === S.mode) return;
    if (mode === "section" && !(await leaveText())) {
      refreshScopeUI();
      return;
    }
    if (mode === "poster") openPoster(S.posterKey && S.byKey.has(S.posterKey) ? S.posterKey : S.selected);
    else openSection(S.editSec);
    announce(bannerText());
  }

  /** Design one poster: from the list, or (fromElsewhere) from another tab, which then moves to the Design tab. */
  async function goPoster(key, fromElsewhere) {
    if (!S.byKey.has(key) || !(await leaveText(key))) return;
    openPoster(key);
    if (fromElsewhere) {
      showTab("design");
      focusEditor(`Design tab: ${S.byKey.get(key).name}, on its own.`);
    }
  }

  async function goSection(secKey, fromElsewhere) {
    if (!(await leaveText())) return;
    openSection(secKey);
    if (fromElsewhere) {
      showTab("design");
      focusEditor(`Design tab. ${bannerText()}`);
    }
  }

  /** After a button on another tab opens the Design tab, which hid that button: carry on from the name at the top. */
  function focusEditor(msg) {
    $("ed-name").focus();
    announce(msg);
  }

  /** Put the current mode back after a reload of the collections or settings. */
  function restoreMode() {
    if (S.mode === "poster") {
      const k = S.posterKey && S.byKey.has(S.posterKey) ? S.posterKey : stageKeyFor(null);
      if (k) openPoster(k);
    } else {
      openSection(S.editSec && S.secByKey.has(S.editSec) ? S.editSec : null);
    }
  }

  // ---- section strip: up to four small posters, in Whole section mode
  const STRIP_MAX = 4;
  const stripActive = () => S.tab === "design" && S.mode === "section" && !!S.selected && !S.gated;

  function stripKeys(secKey) {
    let keys;
    if (secKey) {
      const sec = S.secByKey.get(secKey);
      if (!sec) return [];
      const all = sec.collections.map((x) => x.key);
      keys = all.filter((k) => S.picks.has(k)).concat(all.filter((k) => !S.picks.has(k))).slice(0, STRIP_MAX);
    } else {
      // every poster: the first poster of each of the first sections
      keys = S.sections.map((sec) => stageKeyFor(sec.key)).filter(Boolean).slice(0, STRIP_MAX);
    }
    if (S.selected && !keys.includes(S.selected)) keys = [S.selected].concat(keys.slice(0, STRIP_MAX - 1));
    return keys;
  }

  function refreshStrip() {
    const box = $("strip");
    if (!stripActive()) {
      box.hidden = true;
      S.strip.sec = null;
      S.strip.keys = [];
      return;
    }
    const secKey = S.editSec || "";
    const keys = stripKeys(secKey);
    if (secKey !== S.strip.sec || keys.join("|") !== S.strip.keys.join("|")) {
      buildStrip(secKey, keys);
      stripKick(120);
    }
    box.hidden = false;
    paintStrip();
  }

  function buildStrip(secKey, keys) {
    const sec = secKey && S.secByKey.get(secKey);
    S.strip.sec = secKey;
    S.strip.keys = keys;
    S.strip.cards = new Map();
    $("strip-heading").textContent = sec ? "How it looks across the section" : "How it looks across your sections";
    $("strip-heading").title = sec ? `${keys.length} of ${sec.collections.length} posters in ${sec.name}` : "The first poster from each of your first sections";
    const row = $("strip-row");
    row.textContent = "";
    for (const k of keys) {
      const c = S.byKey.get(k);
      const img = el("img", { alt: "", draggable: "false" });
      const art = el("span", { class: "strip-art" }, [img, el("span", { class: "spinner", "aria-hidden": "true" })]);
      const btn = el("button", { class: "strip-card", type: "button", title: c.name, "aria-label": `Show ${c.name}` }, [art]);
      btn.addEventListener("click", () => selectCollection(k));
      row.append(btn);
      S.strip.cards.set(k, { el: btn, img, art, shownHash: null, failedHash: null });
    }
  }

  function paintStrip() {
    let failed = false;
    for (const [k, card] of S.strip.cards) {
      const hash = hashFor(k);
      const hit = tileFor(k, hash);
      if (card.failedHash === hash) failed = true;
      if (hit && card.shownHash !== hash) {
        card.img.src = hit.image;
        card.shownHash = hash;
      }
      card.el.classList.toggle("is-stale", !!card.shownHash && card.shownHash !== hash);
      card.el.classList.toggle("is-off", !S.picks.has(k));
      const current = k === S.selected;
      card.el.classList.toggle("is-current", current);
      if (current) card.el.setAttribute("aria-current", "true");
      else card.el.removeAttribute("aria-current");
      const stops = accentStops(effective(k).accent, k);
      card.art.style.setProperty("--c1", stops[0]);
      card.art.style.setProperty("--c2", stops[1]);
    }
    $("strip-retry").hidden = !failed;
  }

  /** Try the strip's posters that couldn't be drawn again. */
  function retryStrip() {
    for (const [k, card] of S.strip.cards) {
      card.failedHash = null;
      card.el.title = S.byKey.get(k).name;
    }
    paintStrip();
    pump();
  }

  /** Hold strip renders until edits settle, so the big preview always goes first. */
  function stripKick(delay) {
    S.strip.hold = true;
    clearTimeout(S.strip.timer);
    S.strip.timer = setTimeout(() => {
      S.strip.hold = false;
      if (stripActive()) {
        paintStrip();
        pump();
      }
    }, delay === undefined ? 450 : delay);
  }

  function nextStripJob() {
    if (!stripActive() || S.strip.hold) return null;
    for (const k of S.strip.keys) {
      const card = S.strip.cards.get(k);
      if (!card) continue;
      const hash = hashFor(k);
      if (tileFor(k, hash)) {
        if (card.shownHash !== hash) paintStrip();
        continue;
      }
      if (card.failedHash === hash) continue;
      card.el.classList.add("is-loading");
      return {
        key: k, hash, posters: snapshot(), small: true,
        done: (image) => {
          storeTile(k, hash, image);
          card.el.classList.remove("is-loading");
          paintStrip();
        },
        fail: (e) => {
          card.el.classList.remove("is-loading");
          if (e.status === 0 || e.status === 401) {
            fail(e);  // drawn again once CineSets is back, or after signing in
            return;
          }
          card.failedHash = hash;
          card.el.title = `${S.byKey.get(k).name}: couldn't draw it (${e.message})`;
          paintStrip();
        },
      };
    }
    return null;
  }

  // ------------------------------------------------------------------ editor (Design tab, centre)
  function selectCollection(key) {
    if (!S.byKey.has(key)) return;
    const changed = S.selected !== key;
    if (changed) {
      closeChooser();
      S.preview.candidate = null;
      $("candidate-tag").hidden = true;
      $("stage-fail").hidden = true;
    }
    S.selected = key;
    if (S.mode === "poster") {
      S.posterKey = key;
      writeHash(key);
    } else {
      clearHash();
    }
    renderEditorHead();
    syncLists();
    refreshControls();
    refreshScopeUI();
    refreshPositionButtons();
    if (changed) {
      refreshTextCard();
      S.preview.boxes = { label: null, title: null };
      placeBoxes();
      $("stage").classList.add("is-stale");
      refreshArtworkPanel();
      queueEditorJob();
      const row = S.mode === "poster" && S.ui.drows.get(key);
      if (row && !row.li.hidden && row.li.offsetParent) row.li.scrollIntoView({ block: "nearest" });
    }
  }

  function renderEditorHead() {
    const c = S.byKey.get(S.selected);
    if (!c) return;
    if (S.mode === "section") {
      const sec = S.editSec && S.secByKey.get(S.editSec);
      const n = sec ? sec.collections.length : S.order.length;
      $("ed-name").textContent = sec ? sec.name : "Every section";
      $("ed-kind").textContent = `${n} ${n === 1 ? "poster" : "posters"}`;
      $("ed-section").textContent = `Showing ${c.name}`;
    } else {
      $("ed-name").textContent = c.name;
      $("ed-kind").textContent = c.label || (c.kind === "show" ? "TV shows" : "Films");
      $("ed-section").textContent = c.sectionName || "";
    }
    syncEditorPick();
  }

  function syncEditorPick() {
    const on = !!S.selected && S.picks.has(S.selected);
    const sw = $("ed-picked");
    const poster = S.mode === "poster";
    sw.checked = on;
    sw.disabled = !S.selected;
    $("ed-picked-field").hidden = !poster;
    $("ed-off").hidden = !poster || on || !S.selected;
  }

  function refreshPositionButtons() {
    if (!S.posters) return;
    const own = ownAtScope();
    const from = S.mode === "poster" ? "the section or every poster" : "every poster";
    for (const which of ["label", "title"]) {
      const setting = which + "_position";
      const btn = $("reset-" + which);
      if (own) {
        btn.disabled = !has(own, setting);
        btn.title = `Use the ${which} position from ${from}`;
      } else {
        btn.disabled = shown(setting) == null;
        btn.title = `Put the ${which} back in its default spot`;
      }
    }
  }

  function resetPosition(which) {
    const setting = which + "_position";
    if (ownAtScope()) {
      inherit(setting);
      return;
    }
    setSetting(setting, null, { delay: 0 });
    announce(`${cap(which)} is back in its default spot.`);
  }

  /** Which cards show: the Text and Artwork cards only for one poster, and never the artwork for a streaming poster. */
  function refreshStreamUI() {
    const c = S.byKey.get(S.selected);
    const known = S.preview.key === S.selected;
    const streaming = !!(c && c.streaming) || (known && S.preview.streaming);
    const draggable = !streaming && (!known || S.preview.draggable);
    const poster = S.mode === "poster";
    $("stream-note").hidden = !poster || !streaming;
    $("pos-actions").hidden = !draggable;
    $("artwork-panel").hidden = !poster || streaming;
    $("text-panel").hidden = !poster || !c;
    if ((streaming || !poster) && S.chooser) closeChooser();
  }

  function setStageBusy(on) {
    $("stage").classList.toggle("is-busy", on);
  }

  // ---- preview requests: one at a time, the editor first, then the Preview all grid
  function schedulePreview(delay) {
    clearTimeout(S.preview.timer);
    S.preview.timer = setTimeout(queueEditorJob, delay === undefined ? DEBOUNCE : delay);
  }

  function queueEditorJob() {
    clearTimeout(S.preview.timer);
    S.preview.timer = null;
    if (S.tab !== "design" || !S.selected || !S.posters || S.gated) return;
    const key = S.selected;
    const candidate = S.preview.candidate;
    const text = activeTextDraft();
    const hash = hashFor(key);
    const seq = ++S.preview.seq;
    if (!candidate && !text) {
      const hit = S.cache.get(key);
      if (hit && hit.hash === hash) {
        lane.editor = null;
        S.preview.applied = seq;
        applyEditorPreview(hit, key, seq >= S.preview.boxesSeq && !S.dragging, true);
        setStageBusy(false);
        return;
      }
    }
    const job = { key, candidate, text, hash, seq, posters: snapshot() };
    $("stage-fail").hidden = true;
    job.done = (res) => editorDone(job, res);
    job.fail = (e) => editorFail(job, e);
    lane.editor = job;
    setStageBusy(true);
    pump();
  }

  function pump() {
    if (lane.busy || S.gated || S.offline.on) return;
    let job = null;
    if (lane.editor) {
      job = lane.editor;
      lane.editor = null;
    } else {
      job = nextStripJob() || nextGridJob();
    }
    if (!job) return;
    lane.busy = true;
    const body = { key: job.key, posters: job.posters };
    if (job.candidate) body.artwork = job.candidate;
    if (job.text) body.text = job.text;
    if (job.small) body.size = "small";
    // a small poster comes as a plain picture, kept as a data: URL like the full-size ones
    const call = job.small
      ? api("api/preview", { method: "POST", body, raw: true }).then((res) => res.blob()).then(dataUrl)
      : api("api/preview", { method: "POST", body });
    call.then((res) => job.done(res), (e) => job.fail(e))
      .finally(() => {
        lane.busy = false;
        pump();
      });
  }

  /** Keep at most `most` entries, dropping the ones stored longest ago (a Map keeps the order they were set in). */
  function cachePut(map, key, entry, most) {
    map.delete(key);
    map.set(key, entry);
    while (map.size > most) map.delete(map.keys().next().value);
  }

  function storeCache(key, hash, res) {
    cachePut(S.cache, key, {
      hash, image: res.image, layout: res.layout || {}, draggable: res.draggable, streaming: res.streaming, artwork: res.artwork || null,
    }, CACHE_MAX);
  }

  function storeTile(key, hash, image) {
    cachePut(S.tiles, key, { hash, image }, TILE_MAX);
  }

  /** A picture for a small poster: its own small render, or a full-size one of the same design. */
  function tileFor(key, hash) {
    const t = S.tiles.get(key);
    if (t && t.hash === hash) return t;
    const f = S.cache.get(key);
    return f && f.hash === hash ? f : null;
  }

  const dataUrl = (blob) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("The preview couldn't be read."));
    reader.readAsDataURL(blob);
  });

  function editorDone(job, res) {
    if (!job.candidate && !job.text) {
      storeCache(job.key, job.hash, res);
      if (stripActive()) paintStrip();
    }
    if (job.seq === S.preview.seq) setStageBusy(false);
    if (job.seq <= S.preview.applied || job.key !== S.selected || S.tab !== "design") return;
    S.preview.applied = job.seq;
    applyEditorPreview(res, job.key, job.seq >= S.preview.boxesSeq && !S.dragging, !job.candidate);
  }

  // ---- a collection's words: label, title (or a streaming service's name) and subtitle
  function textOf(c) {
    const t = c.text || {};
    const pick = (a, b) => (a !== undefined && a !== null ? a : b !== undefined && b !== null ? b : "");
    return { label: pick(t.label, c.label), title: pick(t.title, c.title), subtitle: pick(t.subtitle, c.subtitle) };
  }
  /** Keep at most one line break in a title. */
  function oneBreak(v) {
    const parts = String(v).replace(/\r/g, "").split("\n");
    return parts.length > 2 ? parts[0] + "\n" + parts.slice(1).join(" ") : parts.join("\n");
  }
  const readText = () => ({ label: $("tx-label").value, title: oneBreak($("tx-title").value), subtitle: $("tx-subtitle").value });
  const activeTextDraft = () => (S.textDraft && S.textDraft.key === S.selected ? S.textDraft.text : null);

  function setTextError(msg) {
    $("tx-error").hidden = !msg;
    $("tx-error").textContent = msg;
  }

  function refreshTextCard(force) {
    const c = S.byKey.get(S.selected);
    $("text-panel").hidden = !c || S.mode !== "poster";
    if (!c) return;
    const streaming = !!c.streaming;
    $("tx-title-label").textContent = streaming ? "Name" : "Title";
    $("tx-title-hint").textContent = streaming
      ? "Used in the collection's name and when the logo isn't downloaded. Up to 60 characters."
      : "Up to 60 characters. Press Return once for a second line.";
    $("tx-subtitle-label").textContent = streaming ? "Bottom text" : "Subtitle";
    $("tx-subtitle-hint").textContent = streaming ? "The big line at the bottom, for example Popular." : "Can be empty.";
    if (force || !S.textDraft || S.textDraft.key !== c.key) {
      const dropped = !!S.textDraft;
      S.textDraft = null;
      if (dropped) syncDirty();
      const t = textOf(c);
      $("tx-label").value = t.label;
      $("tx-title").value = t.title;
      $("tx-subtitle").value = t.subtitle;
      setTextError("");
    }
    syncTextButtons();
  }

  function syncTextButtons() {
    const c = S.byKey.get(S.selected);
    if (!c) return;
    const dirty = !!activeTextDraft();
    $("tx-save").disabled = !dirty || !!S.textBusy;
    $("tx-revert").hidden = !dirty;
    $("tx-reset").hidden = !(Array.isArray(c.edited_text) && c.edited_text.length) || !!c.custom;
    $("tx-reset").disabled = !!S.textBusy;
  }

  function onTextInput() {
    const c = S.byKey.get(S.selected);
    if (!c) return;
    const ta = $("tx-title");
    const cleaned = oneBreak(ta.value);
    if (cleaned !== ta.value) {
      const pos = ta.selectionStart;
      ta.value = cleaned;
      ta.selectionStart = ta.selectionEnd = Math.min(pos, cleaned.length);
    }
    const text = readText();
    S.textDraft = same(text, textOf(c)) ? null : { key: c.key, text };
    setTextError("");
    syncTextButtons();
    syncDirty();
    schedulePreview(350);
  }

  /** A problem with the words: in the Text card, and as a toast too when the card isn't in view. */
  function textProblem(msg) {
    setTextError(msg);
    if (S.tab !== "design" || $("text-panel").hidden) toast(`Words not saved: ${msg}`, "error");
  }

  /** Save the words typed in the Text card (for whichever poster they were typed for). Says whether they were saved. */
  async function saveText() {
    const d = S.textDraft;
    const c = d && S.byKey.get(d.key);
    if (!c) return true;
    const t = d.text;
    const title = t.title.split("\n").map((s) => s.trim()).filter(Boolean).join("\n");
    if (!title) {
      textProblem(`The ${c.streaming ? "name" : "title"} can't be empty.`);
      return false;
    }
    if (title.replace("\n", "").length > 60) {
      textProblem(`The ${c.streaming ? "name" : "title"} can be up to 60 characters.`);
      return false;
    }
    S.textBusy = true;
    syncTextButtons();
    $("tx-save").classList.add("is-busy");
    try {
      const res = await api("api/text", { method: "POST", body: { key: c.key, label: t.label.trim(), title, subtitle: t.subtitle.trim() } });
      S.textDraft = null;
      toast(res.message || "Text saved.", "ok", 9000);
      await reloadCollections();
      refreshTextCard(true);
      return true;
    } catch (e) {
      if (e.status === 0 || e.status === 401) fail(e);
      else textProblem(e.message);
      return false;
    } finally {
      S.textBusy = false;
      $("tx-save").classList.remove("is-busy");
      syncTextButtons();
      syncDirty();
    }
  }

  /**
   * Before another poster (or Whole section) takes over the editor: words typed in the Text card and not saved
   * are saved, dropped, or kept by staying here, as the person chooses. Resolves true when it's fine to move on.
   */
  async function leaveText(nextKey) {
    const d = S.textDraft;
    if (!d || (nextKey && d.key === nextKey)) return true;
    const c = S.byKey.get(d.key);
    if (!c) {
      S.textDraft = null;
      syncDirty();
      return true;
    }
    const choice = await confirmDialog({
      title: `Save the words for ${c.name}?`,
      text: "You've changed its words in the Text card and haven't saved them yet.",
      ok: "Save words",
      alt: "Don't save",
    });
    if (choice === "ok") return saveText();
    if (choice !== "alt") return false;
    S.textDraft = null;
    refreshTextCard(true);
    syncDirty();
    schedulePreview(0);
    return true;
  }

  async function resetText() {
    const c = S.byKey.get(S.selected);
    if (!c) return;
    const before = textOf(c);
    const fields = (c.edited_text || []).filter((f) => has(before, f));
    S.textBusy = true;
    syncTextButtons();
    try {
      const res = await api("api/text", { method: "POST", body: { key: c.key, reset: true } });
      S.textDraft = null;
      toast(res.message || "Back to the usual words.", "ok", 10000,
        fields.length ? { label: "Undo", run: () => putTextBack(c.key, before, fields) } : null);
      await reloadCollections();
      refreshTextCard(true);
    } catch (e) {
      if (e.status === 0 || e.status === 401) fail(e);
      else setTextError(e.message);
    } finally {
      S.textBusy = false;
      syncTextButtons();
      syncDirty();
    }
  }

  /** Undo "Use the usual words": send back only the words that had been changed, so the rest stay the usual ones. */
  async function putTextBack(key, text, fields) {
    const body = { key };
    for (const f of fields) body[f] = text[f];
    try {
      const res = await api("api/text", { method: "POST", body });
      toast(res.message || "Your words are back.", "ok");
      await reloadCollections();
      if (key === S.selected) refreshTextCard(true);
    } catch (e) {
      fail(e, "Words not put back");
    }
  }

  function editorFail(job, e) {
    if (job.seq === S.preview.seq) setStageBusy(false);
    if (job.candidate && S.preview.candidate === job.candidate) {
      S.preview.candidate = null;
      $("candidate-tag").hidden = true;
    }
    if (e.status === 0 || e.status === 401) {
      fail(e);  // drawn again once CineSets is back, or after signing in
      return;
    }
    if (job.seq !== S.preview.seq || job.key !== S.selected) return;
    $("stage-fail-text").textContent = `Couldn't draw this preview: ${e.message}`;
    $("stage-fail").hidden = false;
  }

  function retryEditor() {
    $("stage-fail").hidden = true;
    queueEditorJob();
  }

  const toRect = (v) => (Array.isArray(v) && v.length === 4 ? v.map(Number) : null);

  function applyEditorPreview(res, key, moveBoxes, real) {
    const c = S.byKey.get(key);
    const img = $("poster");
    if (img.getAttribute("src") !== res.image) img.src = res.image;
    img.alt = `Poster preview for ${c ? c.name : key}`;
    $("stage-empty").hidden = true;
    $("stage-fail").hidden = true;
    $("stage").classList.remove("is-stale");
    $("mini-img").src = res.image;
    S.preview.key = key;
    S.preview.layout = res.layout || {};
    S.preview.streaming = !!res.streaming;
    S.preview.draggable = res.draggable !== false && !res.streaming;
    if (real) S.preview.art = res.artwork || null;
    if (moveBoxes) {
      S.preview.boxes = { label: toRect(S.preview.layout.label), title: toRect(S.preview.layout.title) };
    }
    placeBoxes();
    refreshStreamUI();
    refreshArtworkPanel();
  }

  function resyncBoxes() {
    if (S.preview.applied >= S.preview.boxesSeq && S.preview.layout && S.preview.key === S.selected) {
      S.preview.boxes = { label: toRect(S.preview.layout.label), title: toRect(S.preview.layout.title) };
    }
    placeBoxes();
  }

  function placeBoxes() {
    for (const which of ["label", "title"]) {
      const box = $("box-" + which);
      const r = S.preview.boxes[which];
      const show = !!r && S.preview.draggable && S.preview.key === S.selected;
      box.hidden = !show;
      if (show) {
        box.style.left = r[0] * 100 + "%";
        box.style.top = r[1] * 100 + "%";
        box.style.width = Math.max(0.01, r[2] - r[0]) * 100 + "%";
        box.style.height = Math.max(0.01, r[3] - r[1]) * 100 + "%";
      }
    }
  }

  // ---- drag and keyboard moves
  /** Whether a box can be moved (or resized, for a size setting) at the current scope. */
  function canMove(which, setting) {
    if (!S.selected || !S.preview.boxes[which] || !S.preview.draggable || S.preview.key !== S.selected) return false;
    setting = setting || which + "_position";
    const level = deeperSetter(setting);
    if (level) {
      const verb = setting.endsWith("_size") ? "resize" : "move";
      const what = SETTING_NAMES[setting];
      if (level === "section") {
        const sec = S.secByKey.get(sectionOf(S.selected));
        toast(`${sec.name} has its own ${what}. Choose ${sec.name} in the list to ${verb} it there, or reset it there.`);
      } else {
        toast(`${S.byKey.get(S.selected).name} has its own ${what}. Switch to Each poster to ${verb} it there, or reset it there.`);
      }
      return false;
    }
    return true;
  }

  const currentSize = (which) => Number(effective(S.selected)[SIZE_SETTING[which]]) || 1;

  /** The box scaled by k around its anchor: the bottom edge for the title, the top edge for the label,
      and the left edge (or the centre, when centred) across. */
  function scaledRect(which, r, k, centre) {
    const w = (r[2] - r[0]) * k;
    const h = (r[3] - r[1]) * k;
    const x0 = centre ? (r[0] + r[2]) / 2 - w / 2 : r[0];
    const y0 = which === "title" ? r[3] - h : r[1];
    return [x0, y0, x0 + w, y0 + h];
  }

  function showSizeTip(which, size) {
    const tip = $("box-" + which).querySelector(".box-size");
    tip.hidden = size == null;
    if (size != null) tip.textContent = Math.round(size * 100) + "%";
  }

  function commitSize(which, size, delay) {
    S.preview.boxesSeq = S.preview.seq + 1;
    setSetting(SIZE_SETTING[which], size, { delay });
    announce(`${cap(which)} size ${Math.round(size * 100)}%.`);
  }

  /** Where the block's anchor is now: the position in effect, or the reported box when it is at its default. */
  function basePosition(which) {
    const eff = effective(S.selected);
    const v = eff[which + "_position"];
    if (Array.isArray(v) && v.length >= 2) return [clamp01(v[0]), clamp01(v[1])];
    const r = S.preview.boxes[which];
    const x = eff.align === "centre" ? (r[0] + r[2]) / 2 : r[0];
    return [clamp01(x), clamp01(which === "label" ? r[1] : r[3])];
  }

  function showGuides(x) {
    $("guide-centre").classList.toggle("is-on", x === CENTRE_X);
    $("guide-left").classList.toggle("is-on", x === LEFT_X);
  }

  function moveBoxBy(which, from, dx, dy) {
    S.preview.boxes[which] = [from[0] + dx, from[1] + dy, from[2] + dx, from[3] + dy];
    placeBoxes();
  }

  function onBoxDown(e, which) {
    if (e.button !== 0 || S.dragging) return;
    const resize = !!(e.target && e.target.closest && e.target.closest(".box-handle"));
    if (!canMove(which, resize ? SIZE_SETTING[which] : null)) return;
    e.preventDefault();
    const box = $("box-" + which);
    try { box.setPointerCapture(e.pointerId); } catch (_) { /* synthetic or already released pointer */ }
    box.focus({ preventScroll: true });
    const stage = $("stage").getBoundingClientRect();
    S.dragging = {
      which, mode: resize ? "resize" : "move", id: e.pointerId, sx: e.clientX, sy: e.clientY, w: stage.width, h: stage.height,
      base: basePosition(which), from: S.preview.boxes[which].slice(), moved: false, pos: null,
      size0: currentSize(which), size: null, centre: effective(S.selected).align === "centre",
    };
    box.classList.add(resize ? "is-resizing" : "is-dragging");
    if (resize) showSizeTip(which, S.dragging.size0);
  }

  /** Resize from the corner handle: scale the outline live, keeping its anchor and aspect ratio. */
  function resizeMove(d, e) {
    const r = d.from;
    const w = r[2] - r[0];
    const h = r[3] - r[1];
    // where the dragged corner is now: right edge across, top edge (title) or bottom edge (label) down
    const cx = r[2] + (e.clientX - d.sx) / d.w;
    const cy = (d.which === "title" ? r[1] : r[3]) + (e.clientY - d.sy) / d.h;
    const newW = d.centre ? 2 * (cx - (r[0] + r[2]) / 2) : cx - r[0];
    const newH = d.which === "title" ? r[3] - cy : cy - r[1];
    const sH = w > 0 ? newW / w : 1;
    const sV = h > 0 ? newH / h : 1;
    const s = Math.abs(sH - 1) >= Math.abs(sV - 1) ? sH : sV;
    const [lo, hi] = sizeLimits(SIZE_SETTING[d.which]);
    const size = round(Math.min(hi, Math.max(lo, d.size0 * s)), 2);
    d.size = size;
    S.preview.boxes[d.which] = scaledRect(d.which, r, size / d.size0, d.centre);
    placeBoxes();
    showSizeTip(d.which, size);
  }

  function onBoxMove(e) {
    const d = S.dragging;
    if (!d || e.pointerId !== d.id) return;
    if (!d.moved && Math.hypot(e.clientX - d.sx, e.clientY - d.sy) < 3) return;
    d.moved = true;
    if (d.mode === "resize") {
      resizeMove(d, e);
      return;
    }
    let x = clamp01(d.base[0] + (e.clientX - d.sx) / d.w);
    const y = clamp01(d.base[1] + (e.clientY - d.sy) / d.h);
    let snapped = null;
    if (!e.altKey) {
      for (const g of [CENTRE_X, LEFT_X]) {
        if (Math.abs(x - g) <= SNAP) {
          x = g;
          snapped = g;
          break;
        }
      }
    }
    d.pos = [x, y];
    moveBoxBy(d.which, d.from, x - d.base[0], y - d.base[1]);
    showGuides(snapped);
  }

  function endDrag(e, cancel) {
    const d = S.dragging;
    if (!d || (e && e.pointerId !== undefined && e.pointerId !== d.id)) return;
    S.dragging = null;
    const box = $("box-" + d.which);
    box.classList.remove("is-dragging", "is-resizing");
    try {
      if (box.hasPointerCapture && box.hasPointerCapture(d.id)) box.releasePointerCapture(d.id);
    } catch (_) { /* nothing to release */ }
    showGuides(null);
    showSizeTip(d.which, null);
    const resized = d.mode === "resize" && d.size !== null && d.size !== d.size0;
    if (cancel || !d.moved || (d.mode === "move" && !d.pos) || (d.mode === "resize" && !resized)) {
      if (d.moved) S.preview.boxes[d.which] = d.from;
      resyncBoxes();
      return;
    }
    if (d.mode === "resize") commitSize(d.which, d.size, 60);
    else commitPosition(d.which, d.pos, 60);
  }

  function commitPosition(which, pos, delay) {
    S.preview.boxesSeq = S.preview.seq + 1;
    setSetting(which + "_position", [round(pos[0], 3), round(pos[1], 3)], { delay });
    announce(`${cap(which)} moved to ${Math.round(pos[0] * 100)}% across and ${Math.round(pos[1] * 100)}% down.`);
  }

  function onBoxKey(e, which) {
    if (e.key === "Escape" && S.dragging) {
      endDrag(null, true);
      return;
    }
    const grow = { "+": 1, "=": 1, Add: 1, "-": -1, _: -1, Subtract: -1 }[e.key];
    if (grow && !S.dragging && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      if (!canMove(which, SIZE_SETTING[which])) return;
      const [lo, hi] = sizeLimits(SIZE_SETTING[which]);
      const old = currentSize(which);
      const size = round(Math.min(hi, Math.max(lo, old + grow * SIZE_STEP)), 2);
      if (size === old) return;
      S.preview.boxes[which] = scaledRect(which, S.preview.boxes[which], size / old, effective(S.selected).align === "centre");
      placeBoxes();
      commitSize(which, size, DEBOUNCE);
      return;
    }
    const dirs = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const dir = dirs[e.key];
    if (!dir || S.dragging) return;
    e.preventDefault();
    if (!canMove(which)) return;
    const step = e.shiftKey ? 0.05 : 0.01;
    const base = basePosition(which);
    const pos = [clamp01(base[0] + dir[0] * step), clamp01(base[1] + dir[1] * step)];
    moveBoxBy(which, S.preview.boxes[which].slice(), pos[0] - base[0], pos[1] - base[1]);
    commitPosition(which, pos, DEBOUNCE);
  }

  // ---- artwork
  function refreshArtworkPanel() {
    const c = S.byKey.get(S.selected);
    if (!c) return;
    const art = c.artwork || { mode: "auto", item: null };
    // a mosaic poster: Shuffle picks new tiles, and Choose (one artwork) is off
    const isMosaic = effective(c.key).artwork === "mosaic";
    const status = $("art-status");
    status.textContent = "";
    const seen = S.preview.key === c.key && S.preview.art ? S.preview.art : null;
    const used = seen && seen.name;
    const tiles = seen && Array.isArray(seen.tiles) ? seen.tiles : null;
    if (art.mode === "chosen") {
      status.append("Chosen");
      if (used) status.append(": ", el("strong", { text: used }));
    } else if (tiles) {
      status.append(art.tiles === "chosen" ? "Shuffled, " : "Automatic, ", el("strong", { text: `a mosaic of ${tiles.length} posters` }));
      status.title = tiles.join(", ");
    } else {
      status.append("Automatic");
      if (used) status.append(", currently ", el("strong", { text: used }));
    }
    if (!tiles) status.removeAttribute("title");
    if (seen && seen.note && art.mode !== "chosen") status.append(` (${seen.note})`);
    $("art-mosaic-hint").hidden = !isMosaic;
    const running = S.run.running;
    const blocked = S.artBusy || running;
    const why = running ? "Wait for the run to finish" : "";
    const automatic = art.mode === "auto" && !(isMosaic && art.tiles === "chosen");
    for (const id of ["art-shuffle", "art-choose", "art-auto"]) {
      $(id).disabled = blocked || (id === "art-auto" && automatic) || (id === "art-choose" && isMosaic);
      $(id).title = why;
    }
    if (isMosaic && S.chooser) closeChooser();
    $("chooser-use").disabled = blocked;
    $("art-shuffle").classList.toggle("is-busy", S.artBusy === "shuffle");
  }

  async function artworkAction(action, item, name) {
    const key = S.selected;
    if (!key || S.artBusy) return;
    S.artBusy = action;
    refreshArtworkPanel();
    for (const b of $("chooser-grid").querySelectorAll("button")) b.disabled = true;
    try {
      // the page's settings go too, saved or not, so Shuffle on a poster just made a mosaic picks tiles
      const body = { key, action, posters: snapshot() };
      if (item) body.item = item;
      const res = await api("api/artwork", { method: "POST", body });
      const c = S.byKey.get(key);
      const tilesPicked = res.tiles === "chosen";
      c.artwork = { mode: res.mode || (action === "auto" ? "auto" : "chosen"), item: res.item === undefined ? item || null : res.item };
      if (tilesPicked) c.artwork.tiles = "chosen";
      S.artRev.set(key, (S.artRev.get(key) || 0) + 1);
      S.cache.delete(key);
      S.tiles.delete(key);
      if (action === "choose") toast(name ? `Artwork saved: ${name}.` : "Artwork saved.", "ok");
      else if (action === "shuffle") toast(tilesPicked ? "New mosaic tiles picked and saved." : "New artwork picked and saved.", "ok");
      else toast("Back to automatic artwork. Saved.", "ok");
      if (action === "choose") closeChooser();
      if (key === S.selected) {
        S.preview.candidate = null;
        $("candidate-tag").hidden = true;
        schedulePreview(0);
      }
      gridKick(50);
      if (stripActive()) stripKick();
    } catch (e) {
      fail(e, "Artwork not changed");
    } finally {
      S.artBusy = false;
      for (const b of $("chooser-grid").querySelectorAll("button")) b.disabled = false;
      refreshArtworkPanel();
    }
  }

  function previewCandidate(cand) {
    const id = cand ? cand.id : null;
    if (S.preview.candidate === id) return;
    S.preview.candidate = id;
    const tag = $("candidate-tag");
    tag.hidden = !cand;
    if (cand) tag.textContent = `Previewing ${cand.name || cand.id}`;
    schedulePreview(cand ? 300 : 120);
  }

  /** On a touch screen a tap only previews a title (there's no hover), and Use this keeps it. */
  function touchPick(cand, btn) {
    const ch = S.chooser;
    if (!ch) return;
    ch.picked = cand;
    for (const b of $("chooser-grid").querySelectorAll(".thumb.is-previewed")) b.classList.remove("is-previewed");
    btn.classList.add("is-previewed");
    const use = $("chooser-use");
    use.hidden = false;
    use.textContent = "Use this";
    use.setAttribute("aria-label", `Use ${cand.name || cand.id}`);
    previewCandidate(cand);
    announce(`Previewing ${cand.name || cand.id} on the poster. Use this keeps it.`);
  }

  const canHover = () => window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  async function openChooser() {
    const key = S.selected;
    if (!key) return;
    closeChooser();
    const ch = { key, urls: new Map(), pointer: null, picked: null };
    S.chooser = ch;
    $("chooser-use").hidden = true;
    $("chooser").hidden = false;
    $("art-choose").setAttribute("aria-expanded", "true");
    const grid = $("chooser-grid");
    grid.textContent = "";
    const msg = $("chooser-msg");
    msg.textContent = "";
    msg.append(el("span", { class: "loading" }, [el("span", { class: "spinner", "aria-hidden": "true" }), "Finding artwork. The first time can take a few seconds."]));
    let res;
    try {
      res = await api("api/artwork?key=" + encodeURIComponent(key));
    } catch (e) {
      if (S.chooser === ch) msg.textContent = "Couldn't load the artwork list.";
      fail(e);
      return;
    }
    if (S.chooser !== ch) return;
    const c = S.byKey.get(key);
    if (c && res.mode && (c.artwork.mode !== res.mode || c.artwork.item !== res.item)) {
      c.artwork = { mode: res.mode, item: res.item || null };
      if (res.tiles) c.artwork.tiles = res.tiles;
      refreshArtworkPanel();
      schedulePreview(0);
    }
    if (res.streaming) {
      msg.textContent = "Streaming posters keep their own look; only the text settings apply";
      return;
    }
    const cands = Array.isArray(res.candidates) ? res.candidates : [];
    if (!cands.length) {
      msg.textContent = "No titles to choose from yet for this collection.";
      return;
    }
    msg.textContent = canHover()
      ? "Point at a title (or move to it with Tab) to preview it on the poster, and click it to use it."
      : "Tap a title to preview it on the poster, then Use this to keep it.";
    const inUse = res.mode === "chosen" ? res.item : null;
    const jobs = [];
    for (const cand of cands) {
      const img = el("img", { alt: "", draggable: "false" });
      const imgBox = el("span", { class: "thumb-img" }, [img]);
      if (cand.id === inUse) imgBox.append(el("span", { class: "thumb-check", text: "In use" }));
      const caption = el("span", { class: "thumb-cap" }, [cand.name || cand.id, cand.year ? el("span", { text: ` (${cand.year})` }) : null]);
      const btn = el("button", {
        class: "thumb", type: "button", "aria-pressed": String(cand.id === inUse),
        title: cand.name || cand.id, "aria-label": `Use ${cand.name || cand.id}${cand.year ? " (" + cand.year + ")" : ""}`,
      }, [imgBox, caption]);
      // a mouse previews on hover; a touch (which fires hover and click together) only previews, for Use this
      btn.addEventListener("pointerenter", (e) => { if (e.pointerType === "mouse") previewCandidate(cand); });
      btn.addEventListener("pointerdown", (e) => { ch.pointer = e.pointerType; });
      btn.addEventListener("focus", () => { if (ch.pointer !== "touch" && ch.pointer !== "pen") previewCandidate(cand); });
      btn.addEventListener("click", () => {
        const touch = ch.pointer === "touch" || ch.pointer === "pen";
        ch.pointer = null;
        if (touch) touchPick(cand, btn);
        else artworkAction("choose", cand.id, cand.name);
      });
      grid.append(btn);
      jobs.push({ id: cand.id, img, btn, imgBox });
    }
    loadThumbs(ch, jobs);
  }

  async function loadThumbs(ch, jobs) {
    const queue = jobs.slice();
    const worker = async () => {
      while (queue.length && S.chooser === ch) {
        const job = queue.shift();
        try {
          const res = await api("api/thumb?id=" + encodeURIComponent(job.id), { raw: true });
          const blob = await res.blob();
          if (S.chooser !== ch) return;
          const url = URL.createObjectURL(blob);
          ch.urls.set(job.id, url);
          job.img.src = url;
          job.btn.classList.add("is-loaded");
        } catch (e) {
          if (e.status === 401) return;
          if (S.chooser === ch) job.imgBox.append(el("span", { class: "thumb-fail", text: "No picture" }));
        }
      }
    };
    await Promise.all([worker(), worker(), worker()]);
  }

  function closeChooser() {
    const ch = S.chooser;
    if (!ch) return;
    S.chooser = null;
    for (const u of ch.urls.values()) URL.revokeObjectURL(u);
    $("chooser").hidden = true;
    $("chooser-use").hidden = true;
    $("chooser-grid").textContent = "";
    $("art-choose").setAttribute("aria-expanded", "false");
    if (S.preview.candidate) {
      S.preview.candidate = null;
      $("candidate-tag").hidden = true;
      schedulePreview(0);
    }
  }

  // ------------------------------------------------------------------ tabs
  function showTab(tab, focus) {
    if (!TABS.includes(tab)) return;
    const changed = S.tab !== tab;
    S.tab = tab;
    for (const t of TABS) {
      const btn = $("tab-" + t);
      const on = t === tab;
      btn.setAttribute("aria-selected", String(on));
      btn.tabIndex = on ? 0 : -1;
      $("panel-" + t).hidden = !on;
    }
    $("mini").classList.toggle("is-on", tab === "design");
    if (focus) $("tab-" + tab).focus();
    refreshStrip();
    if (!changed) return;
    if (tab !== "design") {
      closeChooser();
      lane.editor = null;
      setStageBusy(false);
    }
    if (tab === "grid") {
      $("panel-grid").scrollTop = 0;
      buildGrid();
    } else if (tab === "design") {
      queueEditorJob();
    }
  }

  function onTabKey(e) {
    const i = TABS.indexOf(S.tab);
    let next = null;
    if (e.key === "ArrowRight") next = TABS[(i + 1) % TABS.length];
    else if (e.key === "ArrowLeft") next = TABS[(i + TABS.length - 1) % TABS.length];
    else if (e.key === "Home") next = TABS[0];
    else if (e.key === "End") next = TABS[TABS.length - 1];
    if (!next) return;
    e.preventDefault();
    showTab(next, true);
  }

  // ------------------------------------------------------------------ Preview all
  function ensureObserver() {
    const wantRoot = window.matchMedia("(min-width: 1000px)").matches ? $("panel-grid") : null;
    if (S.grid.observer && S.grid.root === wantRoot) return;
    if (S.grid.observer) S.grid.observer.disconnect();
    S.grid.root = wantRoot;
    S.grid.observer = new IntersectionObserver(onIntersect, { root: wantRoot, rootMargin: "240px 0px" });
    for (const card of S.grid.cards.values()) S.grid.observer.observe(card.el);
  }

  function onIntersect(entries) {
    for (const en of entries) {
      const card = S.grid.byEl.get(en.target);
      if (card) card.visible = en.isIntersecting;
    }
    gridKick(30);
  }

  function makeCard(key) {
    const c = S.byKey.get(key);
    const img = el("img", { alt: "", draggable: "false" });
    const ph = el("span", { class: "gcard-ph", "aria-hidden": "true", text: String(c.title || c.name).replace(/\n/g, " ") });
    const art = el("span", { class: "gcard-art" }, [img, ph, el("span", { class: "spinner", "aria-hidden": "true" })]);
    const btn = el("button", { class: "gcard", type: "button", title: `Design ${c.name}` }, [art, el("span", { class: "gcard-name", text: c.name })]);
    btn.addEventListener("click", () => goPoster(key, true));
    return { key, el: btn, img, art, visible: false, shownHash: null, failedHash: null, fail: null };
  }

  function buildGrid() {
    ensureObserver();
    const grid = $("grid");
    const keys = S.order.filter((k) => S.picks.has(k));
    const keep = new Set(keys);
    for (const [k, card] of S.grid.cards) {
      if (!keep.has(k)) {
        S.grid.observer.unobserve(card.el);
        S.grid.byEl.delete(card.el);
        card.el.remove();
        S.grid.cards.delete(k);
      }
    }
    for (const k of keys) {
      let card = S.grid.cards.get(k);
      if (!card) {
        card = makeCard(k);
        S.grid.cards.set(k, card);
        S.grid.byEl.set(card.el, card);
        S.grid.observer.observe(card.el);
      }
      grid.append(card.el);
    }
    S.grid.order = keys;
    $("grid-empty").hidden = keys.length > 0;
    refreshGrid();
  }

  function gridKick(delay) {
    if (S.tab !== "grid") return;
    clearTimeout(S.grid.timer);
    S.grid.timer = setTimeout(refreshGrid, delay === undefined ? GRID_DEBOUNCE : delay);
  }

  function showCard(card, entry, hash) {
    if (card.img.getAttribute("src") !== entry.image) card.img.src = entry.image;
    card.el.classList.add("has-image");
    card.shownHash = hash;
    clearCardFail(card);
  }

  function clearCardFail(card) {
    if (!card.fail) return;
    card.fail.remove();
    card.fail = null;
    card.el.removeAttribute("aria-describedby");
  }

  function refreshGrid() {
    if (S.tab !== "grid") return;
    let fresh = 0;
    for (const key of S.grid.order) {
      const card = S.grid.cards.get(key);
      const hash = hashFor(key);
      const hit = tileFor(key, hash);
      if (hit && card.shownHash !== hash) showCard(card, hit, hash);
      card.el.classList.toggle("is-stale", !!card.shownHash && card.shownHash !== hash);
      card.el.classList.toggle("is-selected", key === S.selected);
      if (card.shownHash === hash) fresh++;
      const stops = accentStops(effective(key).accent, key);
      card.art.style.setProperty("--c1", stops[0]);
      card.art.style.setProperty("--c2", stops[1]);
    }
    updateGridStatus(fresh);
    pump();
  }

  function updateGridStatus(fresh) {
    if (fresh === undefined) {
      fresh = 0;
      for (const key of S.grid.order) if (S.grid.cards.get(key).shownHash === hashFor(key)) fresh++;
    }
    const n = S.grid.order.length;
    $("grid-status").textContent = n ? `${fresh} of ${n} rendered${fresh < n ? ". Scroll to render the rest" : ""}` : "";
    $("grid-retry").hidden = !S.grid.order.some((key) => S.grid.cards.get(key).fail);
  }

  /** Try the posters that couldn't be drawn again. */
  function retryGrid() {
    for (const card of S.grid.cards.values()) {
      card.failedHash = null;
      clearCardFail(card);
    }
    refreshGrid();
  }

  function nextGridJob() {
    if (S.tab !== "grid") return null;
    for (const key of S.grid.order) {
      const card = S.grid.cards.get(key);
      if (!card || !card.visible) continue;
      const hash = hashFor(key);
      const hit = tileFor(key, hash);
      if (hit) {
        if (card.shownHash !== hash) showCard(card, hit, hash);
        continue;
      }
      if (card.failedHash === hash) continue;
      card.el.classList.add("is-loading");
      return {
        key, hash, posters: snapshot(), small: true,
        done: (res) => gridDone(card, key, hash, res),
        fail: (e) => gridFail(card, hash, e),
      };
    }
    return null;
  }

  function gridDone(card, key, hash, image) {
    storeTile(key, hash, image);
    card.el.classList.remove("is-loading");
    if (S.grid.cards.get(key) !== card) return;
    showCard(card, S.tiles.get(key), hash);
    card.el.classList.toggle("is-stale", hashFor(key) !== hash);
    updateGridStatus();
  }

  function gridFail(card, hash, e) {
    card.el.classList.remove("is-loading");
    if (e.status === 0 || e.status === 401) {
      fail(e);  // drawn again once CineSets is back, or after signing in
      return;
    }
    card.failedHash = hash;
    if (!card.fail) {
      card.fail = el("span", { class: "gcard-fail", id: `gfail-${card.key}` });
      card.art.append(card.fail);
      card.el.setAttribute("aria-describedby", card.fail.id);
    }
    card.fail.textContent = `Couldn't render: ${e.message}`;
    updateGridStatus();
  }

  // ------------------------------------------------------------------ unsaved changes, save, discard, conflicts
  function adoptSaved(settings) {
    S.saved.posters = normalisePosters(withDefaults(settings && settings.posters));
    S.saved.collections = clone(settings && settings.collections) || { sections: "all", include: [], exclude: [] };
    S.saved.picks = derivePicks(S.saved.collections);
    S.saved.version = settings && settings.version !== undefined ? settings.version : null;
    S.saved.limits = normaliseLimits(settings && settings.limits);
  }

  function showConflict(msg) {
    $("conflict-text").textContent = `${msg || "Your settings file changed since the dashboard loaded it."} Reload to get the latest settings, or keep editing.`;
    $("conflict").hidden = false;
  }

  function hideConflict() {
    $("conflict").hidden = true;
  }

  async function reloadSettings() {
    if (S.dirty) {
      const ok = await confirmDialog({
        title: "Reload settings?",
        text: "This loads the latest settings and picks from your config file. Your unsaved edits here are discarded.",
        ok: "Reload",
        danger: true,
      });
      if (!ok) return;
    }
    const btn = $("conflict-reload");
    btn.disabled = true;
    try {
      const [settings, cols] = await Promise.all([api("api/settings"), api("api/collections")]);
      applyLoaded(settings, cols);
      hideConflict();
      toast("Settings reloaded.", "ok");
    } catch (e) {
      fail(e, "Couldn't reload");
    } finally {
      btn.disabled = false;
    }
  }

  function dirtyState() {
    const now = normalisePosters(S.posters);
    const strip = (p) => {
      const g = { ...p };
      for (const k of LAYER_KEYS) delete g[k];
      return g;
    };
    return {
      style: !same(strip(now), strip(S.saved.posters)),
      sections: !same(now.sections, S.saved.posters.sections),
      overrides: !same(now.overrides, S.saved.posters.overrides),
      picks: !setsEqual(S.picks, S.saved.picks),
      limits: !same(normaliseLimits(S.limits), S.saved.limits),
    };
  }

  /** Anything not saved yet: settings (S.dirty) or words typed in the Text card. */
  const unsaved = () => S.dirty || !!S.textDraft;

  function syncDirty() {
    if (!S.posters) return;
    const d = dirtyState();
    const parts = [];
    if (d.style) parts.push("all posters");
    if (d.sections) parts.push("section designs");
    if (d.overrides) parts.push("collection designs");
    if (d.picks) parts.push("collections on or off");
    if (d.limits) parts.push("collection sizes");
    S.dirty = parts.length > 0;
    const draft = S.textDraft && S.byKey.get(S.textDraft.key);
    if (draft) parts.push(`the words for ${draft.name}`);
    const any = unsaved();
    const busy = S.saving || S.textBusy;
    for (const id of ["dirty", "m-dirty"]) {
      const ind = $(id);
      ind.classList.toggle("is-dirty", any);
      ind.textContent = "";
      // the short word shows where the topbar is narrow, so the state is never just a coloured dot
      ind.append(el("span", { class: "dirty-text", text: any ? "Unsaved changes" : "All changes saved" }),
        el("span", { class: "dirty-short", text: any ? "Unsaved" : "Saved" }));
      ind.title = any ? `Unsaved: ${listText(parts)}` : "Everything is saved";
    }
    $("dirty").setAttribute("aria-label", any ? `Unsaved changes: ${listText(parts)}` : "All changes saved");
    for (const id of ["save-btn", "m-save"]) $(id).disabled = !any || busy;
    $("discard-btn").disabled = !any || busy;
    document.title = any ? "CineSets (unsaved)" : "CineSets";
  }

  function afterBulkChange() {
    syncLists();
    settingsChanged({ delay: 0 });
    if (S.tab === "grid") buildGrid();
  }

  /** Save everything that isn't saved: the settings, then any words typed in the Text card. Says whether it all saved. */
  async function save() {
    if (S.saving || S.textBusy || !S.posters) return false;
    if (S.dirty && !(await saveSettings())) return false;
    if (S.textDraft) return saveText();
    return true;
  }

  async function saveSettings() {
    S.saving = true;
    syncDirty();
    const btn = $("save-btn");
    btn.classList.add("is-busy");
    $("m-save").classList.add("is-busy");
    const sentPosters = normalisePosters(S.posters);
    const sentPicks = new Set(S.picks);
    const sentLimits = normaliseLimits(S.limits);
    const picksChanged = !setsEqual(sentPicks, S.saved.picks);
    const body = {
      posters: sentPosters,
      collections: picksChanged ? buildCollections(sentPicks) : clone(S.saved.collections),
      limits: sentLimits,
      version: S.saved.version,
    };
    try {
      const res = await api("api/save", { method: "POST", body });
      if (res.saved === false) {
        toast(res.message || "Nothing was saved.", "info", 6000);
        return true;
      }
      toast(res.message || "Saved.", "ok");
      hideConflict();
      // read back what the server stored (it may tidy values); its version matches that content
      let fresh = null;
      try {
        fresh = await api("api/settings");
      } catch (_) { /* fall back to what was sent */ }
      const untouched = same(normalisePosters(S.posters), sentPosters) && setsEqual(S.picks, sentPicks)
        && same(normaliseLimits(S.limits), sentLimits);
      adoptSaved(fresh || { posters: body.posters, collections: body.collections, limits: body.limits, version: res.version });
      if (!S.saved.version && res.version) S.saved.version = res.version;
      if (untouched) {
        S.posters = clone(S.saved.posters);
        S.picks = new Set(S.saved.picks);
        S.limits = clone(S.saved.limits);
        S.history.base = snapshot();  // the server's tidy copy of the same design is not a step to undo
      }
      syncSizes();
      afterBulkChange();
      return true;
    } catch (e) {
      if (e.status === 409) showConflict(e.message);
      else fail(e, "Not saved");
      return false;
    } finally {
      S.saving = false;
      btn.classList.remove("is-busy");
      $("m-save").classList.remove("is-busy");
      syncDirty();
    }
  }

  async function discard() {
    if (!unsaved() || S.saving || S.textBusy) return;
    const ok = await confirmDialog({
      title: "Discard unsaved changes?",
      text: "Designs, which collections are on, sizes and words typed in the Text card go back to your last save. "
        + "Artwork choices are already kept and stay as they are. Undo can bring back the designs.",
      ok: "Discard",
      danger: true,
    });
    if (!ok) return;
    S.posters = clone(S.saved.posters);
    S.picks = new Set(S.saved.picks);
    S.limits = clone(S.saved.limits);
    if (S.textDraft) {
      S.textDraft = null;
      refreshTextCard(true);
    }
    afterBulkChange();
    syncSizes();
    toast("Changes discarded.");
  }

  // ------------------------------------------------------------------ running CineSets
  /** The media server, for messages: "your Emby server", so it's never confused with CineSets itself. */
  function serverName() {
    const kind = S.info && S.info.server;
    return kind && kind !== "demo" ? `your ${cap(kind)} server` : "your media server";
  }

  function syncRunButtons() {
    const can = !!S.info && S.info.can_apply !== false;
    const running = S.run.running;
    const why = !can ? "Demo mode: running CineSets is switched off" : running ? "A run is in progress" : "";
    for (const id of ["plan-btn", "apply-btn", "m-apply"]) {
      $(id).disabled = !can || running;
      $(id).title = why || (id === "plan-btn" ? "See what would change, without changing anything" : `Create and update collections on ${serverName()}`);
    }
    $("run-wrap").title = why;
    refreshArtworkPanel();
  }

  function showLog(show) {
    $("runlog").hidden = !show;
    $("app").classList.toggle("has-log", show);
    $("log-btn").setAttribute("aria-expanded", String(show));
    $("log-btn").setAttribute("aria-label", show ? "Hide the run log" : "Show the run log");
    if (show) {
      const pre = $("runlog-text");
      pre.scrollTop = pre.scrollHeight;
    }
  }

  function resetLog() {
    $("runlog-text").textContent = "";
    S.run.shown = 0;
    S.run.lost = false;
  }

  function appendLog(lines) {
    const pre = $("runlog-text");
    const stick = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 48;
    pre.append(document.createTextNode(lines.join("\n") + "\n"));
    if (stick || $("runlog").hidden) pre.scrollTop = pre.scrollHeight;
  }

  /**
   * How the last run went, from what it said: its Summary line, its lines starting with !! and whether it stopped
   * early. Any of those, or an exit code other than 0, means it finished with problems. Output from before runs
   * had a Summary line simply leaves that part out.
   */
  function runOutcome() {
    const r = S.run;
    const what = r.command === "apply" ? "Apply" : "Dry run";
    if (r.lost) {
      return {
        bad: true,
        text: `The dashboard restarted during the ${what.toLowerCase()}, so how it ended isn't known. Look at the end of `
          + "the CineSets log (the terminal, docker compose logs cinesets-web or journalctl -u cinesets-web), or run it again.",
      };
    }
    const bad = r.exit !== 0 || r.problems > 0 || !!r.stopped;
    const parts = [];
    if (r.summary) parts.push(r.summary);
    if (r.stopped) parts.push(`stopped early: ${r.stopped}`);
    if (r.problems) parts.push(`${r.problems} ${r.problems === 1 ? "problem" : "problems"} in the log (the lines starting with !!)`);
    if (bad && !r.problems && !r.stopped) parts.push(`it ended with error code ${r.exit}`);
    const head = bad ? `${what} finished with problems` : `${what} finished`;
    return { bad, text: parts.length ? `${head}: ${parts.join("; ")}.` : `${head}.` };
  }

  function showRunStatus() {
    const status = $("run-status");
    status.className = "run-status";
    status.textContent = "";
    if (S.run.running) {
      status.classList.add("is-running");
      status.append(el("span", { class: "spinner", "aria-hidden": "true" }), S.run.command === "apply" ? `Applying to ${serverName()}` : "Dry run in progress");
      return;
    }
    if (S.run.exit === null && !S.run.lost) return;
    const out = runOutcome();
    status.classList.add(out.bad ? "is-bad" : "is-ok");
    status.textContent = out.text;
  }

  /** The dashboard restarted while a run was on show: it has no record of that run, so keep its log and say so. */
  function runLost() {
    S.run.lost = true;
    S.run.running = false;
    appendLog(["", "(The dashboard restarted here, so the rest of this run's output isn't shown.)"]);
    showRunStatus();
    syncRunButtons();
    toast(runOutcome().text, "error", 0, { label: "Show the log", run: () => showLog(true) });
  }

  /** New lines and the state of the run, from api/run?since=(the lines already shown). */
  function applyRun(r) {
    const was = S.run.running;
    if (r.run && r.run !== S.run.id) {  // a run the page didn't know: started in another tab, or after a restart
      resetLog();
      S.run.id = r.run;
    } else if (!r.run && (S.run.id || was)) {
      if (was) runLost();
      return;
    }
    const lines = Array.isArray(r.lines) ? r.lines : [];
    if (r.skipped) appendLog([`(${r.skipped} earlier ${r.skipped === 1 ? "line isn't" : "lines aren't"} kept)`]);
    if (lines.length) appendLog(lines);
    S.run.shown = Number.isFinite(r.total) ? r.total : S.run.shown + lines.length;
    S.run.running = !!r.running;
    S.run.command = r.command || S.run.command;
    S.run.exit = r.exit === undefined ? null : r.exit;
    S.run.problems = Number(r.problems) || 0;
    S.run.summary = r.summary || null;
    S.run.stopped = r.stopped || null;
    showRunStatus();
    if (was && !S.run.running) {
      const out = runOutcome();
      const said = S.run.summary ? `: ${S.run.summary}` : "";
      if (out.bad) toast(out.text, "error", 0, { label: "Show the log", run: () => showLog(true) });
      else if (S.run.command === "apply") toast(`Applied to ${serverName()}${said}.`, "ok", 8000);
      else toast(`Dry run finished${said}. See the log for what would change.`, "ok", 8000);
    }
    syncRunButtons();
  }

  async function pollRun() {
    clearTimeout(S.run.timer);
    if (S.gated || S.offline.on) return;
    try {
      let r = await api("api/run?since=" + S.run.shown);
      // a different run from the one on show: read it from its first line
      if (r.run && r.run !== S.run.id && S.run.shown) r = await api("api/run?since=0");
      applyRun(r);
    } catch (e) {
      fail(e, "Couldn't read the run log");
      if (e.status === 0) return;  // the offline banner reads it again when CineSets is back
    }
    if (S.run.running && !S.gated) S.run.timer = setTimeout(pollRun, POLL_MS);
  }

  async function startRun(command) {
    if (S.run.running) return;
    if (command === "apply") {
      if (unsaved()) {
        const choice = await confirmDialog({
          title: "Save, then apply?",
          text: "Apply uses your saved settings, and you have unsaved changes. Save them first to include them, or apply "
            + `what's saved now. Either way, this creates and updates collections on ${serverName()}.`,
          ok: "Save and apply",
          alt: "Apply without saving",
        });
        if (!choice || (choice === "ok" && !(await save()))) return;
      } else {
        const ok = await confirmDialog({
          title: `Apply to ${serverName()}?`,
          text: `This creates and updates collections on ${serverName()} with your saved settings.`,
          ok: "Apply",
        });
        if (!ok) return;
      }
    } else if (unsaved()) {
      toast("The dry run uses your saved settings. Unsaved changes aren't included.");
    }
    try {
      await api("api/run", { method: "POST", body: { command } });
      resetLog();
      Object.assign(S.run, { id: null, running: true, command, exit: null, problems: 0, summary: null, stopped: null });
      showRunStatus();
      syncRunButtons();
      showLog(true);
      S.run.timer = setTimeout(pollRun, 400);
    } catch (e) {
      fail(e, "Couldn't start");
      if (e.status === 409) {
        showLog(true);
        pollRun();
      }
    }
  }

  // ------------------------------------------------------------------ start-up
  function setupData(cols) {
    S.sections = (cols.sections || []).map((sec) => ({ ...sec, collections: (sec.collections || []).slice() }));
    S.byKey.clear();
    S.secByKey.clear();
    S.order = [];
    for (const sec of S.sections) {
      S.secByKey.set(sec.key, sec);
      for (const c of sec.collections) {
        c.section = sec.key;
        c.sectionName = sec.name;
        if (!c.artwork) c.artwork = { mode: "auto", item: null };
        S.byKey.set(c.key, c);
        S.order.push(c.key);
      }
    }
  }

  function renderTop() {
    const info = S.info;
    const server = info.server ? cap(info.server) : "";
    $("brand-meta").textContent = [info.version ? "v" + info.version : "", server, info.config].filter(Boolean).join("  ·  ");
    $("demo-badge").hidden = !info.demo;
    $("signout-btn").hidden = !signInUsed();
  }

  /** Sign-in is off in demo mode, or when the server has it switched off. */
  const signInUsed = () => !!S.session && !S.session.demo && S.session.sign_in !== false && !(S.info && S.info.demo);

  // ---- the URL hash names the open collection (#m-action); #key=... is a one-off sign-in link
  function hashValue() {
    try {
      return decodeURIComponent(window.location.hash.replace(/^#/, ""));
    } catch (_) {
      return "";
    }
  }

  function keyFromHash() {
    const h = hashValue();
    return h && !h.startsWith("key=") && S.byKey.has(h) ? h : null;
  }

  function writeHash(key) {
    if (!key || window.location.hash === "#" + key) return;
    history.replaceState(null, "", window.location.pathname + window.location.search + "#" + key);
  }

  /** Whole section mode has no poster in the address, so a reload doesn't jump to Each poster. */
  function clearHash() {
    if (!window.location.hash || hashValue().startsWith("key=")) return;
    history.replaceState(null, "", window.location.pathname + window.location.search);
  }


  /** Put freshly loaded settings and collections in place (first load, or Reload settings after a conflict). */
  function applyLoaded(settings, cols) {
    const keep = S.selected;
    setupData(cols);
    adoptSaved(settings);
    S.posters = clone(S.saved.posters);
    S.picks = new Set(S.saved.picks);
    S.limits = clone(S.saved.limits);
    S.cache.clear();
    S.tiles.clear();
    if (S.grid.observer) S.grid.observer.disconnect();
    S.grid.observer = null;
    S.grid.cards.clear();
    S.grid.byEl.clear();
    S.grid.order = [];
    $("grid").textContent = "";
    S.strip.sec = null;
    S.strip.keys = [];
    renderCollections();
    renderDesignList();
    renderListsPanel();
    fillNcSections();
    syncSizes();
    S.selected = null;
    // a #key in the address opens that poster; otherwise carry on in the current mode (Every section at first)
    const fromHash = keyFromHash();
    if (fromHash) {
      S.mode = "poster";
      S.posterKey = fromHash;
    } else if (!keep) {
      S.posterKey = null;
    }
    if (S.editSec && !S.secByKey.has(S.editSec)) S.editSec = null;
    if (S.order.length) {
      restoreMode();
    } else {
      $("ed-name").textContent = "No collections found";
      $("stage-empty").textContent = "Nothing to preview";
    }
    syncLists();
    syncDirty();
    refreshScopeUI();
    historyReset();
    if (S.tab === "grid") buildGrid();
  }

  // ---- first run: three steps, until they're dismissed (remembered in this browser when it lets us)
  function showIntro() {
    let done = false;
    try {
      done = window.localStorage.getItem(INTRO_KEY) === "1";
    } catch (_) { /* storage blocked: show it */ }
    $("intro-server").textContent = serverName();
    $("intro").hidden = done;
  }

  function closeIntro() {
    $("intro").hidden = true;
    try {
      window.localStorage.setItem(INTRO_KEY, "1");
    } catch (_) { /* not remembered, so it shows again next time */ }
  }

  // ---- phones: a small copy of the poster while it's scrolled out of view on the Design tab
  function watchStage() {
    if (typeof IntersectionObserver !== "function") return;
    new IntersectionObserver((entries) => {
      for (const en of entries) $("mini").classList.toggle("is-away", !en.isIntersecting);
    }, { threshold: 0.15 }).observe($("stage"));
  }

  /** True when focus is somewhere that has its own undo (a text field), so Ctrl or Cmd + Z is left to it. */
  function typing(t) {
    if (!t || !t.tagName) return false;
    if (t.isContentEditable || t.tagName === "TEXTAREA" || t.tagName === "SELECT") return true;
    return t.tagName === "INPUT" && !["range", "radio", "checkbox", "color", "button", "submit"].includes(t.type);
  }

  async function startApp() {
    let info;
    let settings;
    let cols;
    try {
      [info, settings, cols] = await Promise.all([api("api/info"), api("api/settings"), api("api/collections")]);
    } catch (e) {
      if (e.status === 401 || (S.gated && !$("signin").hidden)) return;
      showError(`The dashboard couldn't load. ${e.message}`, true);
      return;
    }
    S.info = info;
    S.gated = false;
    renderTop();
    renderControls();
    renderNewCollection();
    applyLoaded(settings, cols);
    S.loaded = true;
    $("gate").hidden = true;
    $("boot").hidden = true;
    $("app").hidden = false;
    syncRunButtons();
    showIntro();
    try {
      const r = await api("api/run?since=0");
      applyRun(r);
      if (r.running) {
        showLog(true);
        S.run.timer = setTimeout(pollRun, POLL_MS);
      }
    } catch (e) {
      fail(e, "Couldn't read the run status");
    }
  }

  function wire() {
    $("gate-retry").addEventListener("click", () => window.location.reload());
    $("signin").addEventListener("submit", submitSignIn);
    $("signout-btn").addEventListener("click", signOut);
    $("save-btn").addEventListener("click", save);
    $("discard-btn").addEventListener("click", discard);
    $("plan-btn").addEventListener("click", () => startRun("plan"));
    $("apply-btn").addEventListener("click", () => startRun("apply"));
    $("log-btn").addEventListener("click", () => showLog($("runlog").hidden));
    $("runlog-close").addEventListener("click", () => showLog(false));
    $("conflict-reload").addEventListener("click", reloadSettings);
    $("conflict-keep").addEventListener("click", hideConflict);
    $("offline-retry").addEventListener("click", reconnect);
    $("intro-close").addEventListener("click", closeIntro);
    $("intro-collections").addEventListener("click", () => showTab("collections", true));
    $("undo-btn").addEventListener("click", undo);
    $("redo-btn").addEventListener("click", redo);
    $("stage-retry").addEventListener("click", retryEditor);
    $("strip-retry").addEventListener("click", retryStrip);
    $("grid-retry").addEventListener("click", retryGrid);
    $("m-save").addEventListener("click", save);
    $("m-apply").addEventListener("click", () => startRun("apply"));
    $("mini").addEventListener("click", () => {
      $("stage").scrollIntoView({ block: "center" });
      $("ed-name").focus({ preventScroll: true });
    });
    watchStage();

    for (const t of TABS) {
      const btn = $("tab-" + t);
      btn.addEventListener("click", () => showTab(t));
      btn.addEventListener("keydown", onTabKey);
    }

    $("col-search").addEventListener("input", (e) => {
      S.colSearch = e.target.value;
      S.colSearchClosed.clear();
      syncLists();
    });
    $("list-search").addEventListener("input", (e) => {
      if (S.mode === "section") {
        S.secSearch = e.target.value;
      } else {
        S.listSearch = e.target.value;
        S.listSearchClosed.clear();
      }
      syncLists();
    });
    $("lists-search").addEventListener("input", (e) => {
      S.lpSearch = e.target.value;
      S.lpSearchClosed.clear();
      syncListsPanel();
    });
    let lastMost = null;
    $("most-switch").addEventListener("change", (e) => {
      if (e.target.checked) setMost(lastMost || defaultLimit());
      else {
        lastMost = S.limits.most;
        setMost(null);
      }
    });
    const most = $("most-input");
    most.addEventListener("change", () => {
      const raw = most.value.trim();
      const n = Number(raw);
      if (raw === "" || !Number.isFinite(n)) syncSizes();
      else setMost(n);
    });
    most.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        most.blur();
      }
    });
    for (const r of document.querySelectorAll('input[name="nc-mode"]')) r.addEventListener("change", syncNcMode);
    for (const r of document.querySelectorAll('input[name="nc-type"]')) {
      r.addEventListener("change", () => {
        S.nc.typeTouched = true;
        if (S.nc.checked) showNcChecked();
      });
    }
    $("nc-limit").addEventListener("input", syncNcWarn);
    $("nc-ex-select").addEventListener("change", () => { if (S.nc.checked) showNcChecked(); });
    $("nc-ex-search").addEventListener("input", fillExisting);
    $("nc-ex-add").addEventListener("click", ncAddExisting);
    $("nc-ex-select").addEventListener("dblclick", ncAddExisting);
    for (const id of ["tx-label", "tx-title", "tx-subtitle"]) $(id).addEventListener("input", onTextInput);
    $("tx-save").addEventListener("click", saveText);
    $("tx-reset").addEventListener("click", resetText);
    $("tx-revert").addEventListener("click", () => {
      S.textDraft = null;
      refreshTextCard(true);
      syncDirty();
      schedulePreview(0);
    });
    $("nc-add-list").addEventListener("click", () => ncRow().focus());
    $("nc-check").addEventListener("click", ncCheck);
    $("nc-form").addEventListener("submit", ncCreate);
    $("nc-twolines").addEventListener("change", (e) => {
      $("nc-title2").hidden = !e.target.checked;
      if (e.target.checked) $("nc-title2").focus();
    });
    $("nc-section").addEventListener("change", (e) => {
      $("nc-section-name").hidden = e.target.value !== "__new";
      if (e.target.value === "__new") $("nc-section-name").focus();
    });
    $("all-on").addEventListener("click", () => setPicked(matchKeys(S.colSearch), true));
    $("all-off").addEventListener("click", () => setPicked(matchKeys(S.colSearch), false));
    $("ed-picked").addEventListener("change", (e) => { if (S.selected) setPicked([S.selected], e.target.checked); });

    for (const r of document.querySelectorAll('input[name="mode"]')) {
      r.addEventListener("change", () => { if (r.checked) setMode(r.value); });
    }
    $("scope-reset").addEventListener("click", resetScope);

    for (const which of ["label", "title"]) {
      const box = $("box-" + which);
      box.addEventListener("pointerdown", (e) => onBoxDown(e, which));
      box.addEventListener("pointermove", onBoxMove);
      box.addEventListener("pointerup", (e) => endDrag(e, false));
      box.addEventListener("pointercancel", (e) => endDrag(e, true));
      box.addEventListener("keydown", (e) => onBoxKey(e, which));
      $("reset-" + which).addEventListener("click", () => resetPosition(which));
    }
    $("poster").addEventListener("dragstart", (e) => e.preventDefault());

    $("art-shuffle").addEventListener("click", () => artworkAction("shuffle"));
    $("art-auto").addEventListener("click", () => artworkAction("auto"));
    $("art-choose").addEventListener("click", () => (S.chooser ? closeChooser() : openChooser()));
    $("chooser-close").addEventListener("click", () => {
      closeChooser();
      $("art-choose").focus();
    });
    const cgrid = $("chooser-grid");
    cgrid.addEventListener("pointerleave", (e) => {
      if (e.pointerType === "mouse" && !cgrid.contains(document.activeElement)) previewCandidate(null);
    });
    cgrid.addEventListener("focusout", (e) => {
      const touchPicked = S.chooser && S.chooser.picked;
      if (!$("chooser").contains(e.relatedTarget) && !touchPicked && !cgrid.matches(":hover")) previewCandidate(null);
    });
    $("chooser-use").addEventListener("click", () => {
      const cand = S.chooser && S.chooser.picked;
      if (cand) artworkAction("choose", cand.id, cand.name);
    });

    document.addEventListener("keydown", (e) => {
      const key = (e.key || "").toLowerCase();
      if ((e.metaKey || e.ctrlKey) && !e.altKey && key === "s") {
        if ($("app").hidden) return;
        e.preventDefault();
        save();
      } else if ((e.metaKey || e.ctrlKey) && !e.altKey && (key === "z" || (key === "y" && e.ctrlKey && !e.metaKey && !e.shiftKey))) {
        // design edits on the Design and Preview all tabs; text fields keep their own undo
        if ($("app").hidden || $("confirm").open || typing(e.target) || (S.tab !== "design" && S.tab !== "grid")) return;
        e.preventDefault();
        if (key === "z" && !e.shiftKey) undo();
        else redo();
      } else if (e.key === "Escape" && S.chooser && $("chooser").contains(document.activeElement)) {
        closeChooser();
        $("art-choose").focus();
      }
    });
    window.addEventListener("beforeunload", (e) => {
      if (unsaved()) {
        e.preventDefault();
        e.returnValue = "";
      }
    });
    window.addEventListener("hashchange", () => {
      const key = keyFromHash();
      if (key && S.loaded && !(S.mode === "poster" && key === S.selected)) goPoster(key, true);
    });
    const mq = window.matchMedia("(min-width: 1000px)");
    const onMq = () => { if (S.tab === "grid") ensureObserver(); };
    if (mq.addEventListener) mq.addEventListener("change", onMq);
  }

  async function init() {
    wire();
    // a sign-in link carries the key in the fragment, which never reaches the server or its logs
    let loginError = "";
    const h = hashValue();
    if (h.startsWith("key=")) {
      const key = h.slice(4);
      const login = api("api/login", { method: "POST", body: { key }, quiet401: true });
      history.replaceState(null, "", window.location.pathname);
      try {
        await login;
      } catch (e) {
        loginError = e.status === 401 ? `That sign-in link didn't work. ${e.message}` : e.message;
      }
    }
    try {
      S.session = await api("api/session", { quiet401: true });
    } catch (e) {
      showError(e.status === 0 ? UNREACHABLE : `The dashboard couldn't load. ${e.message}`, true);
      return;
    }
    $("signout-btn").hidden = !signInUsed();
    if (S.session.signed_in || !signInUsed()) await startApp();
    else showSignIn("", loginError);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
