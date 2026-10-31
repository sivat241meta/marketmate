// Task 134: a remembered market must never bounce visitors back home.
//
// Loads the real app/web/static/popups.js (and locate.js) with a fake
// DOM and checks: with a remembered area, page init on /new, /sellers,
// /how, /market and /s/x never navigates (it only labels the header
// location button); on "/" it applies ?area= once. goArea on a shop
// page stays on the page. Exit 0 on success, non-zero on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const POPUPS_SRC = fs.readFileSync(
  path.join(ROOT, "app/web/static/popups.js"), "utf8");
const LOCATE_SRC = fs.readFileSync(
  path.join(ROOT, "app/web/static/locate.js"), "utf8");

const REMEMBERED = "Koyambedu Market, Chennai";

// --- tiny fake DOM ----------------------------------------------------

function fakeEl(tag) {
  return {
    tag, textContent: "", hidden: false, dataset: {},
    children: [], attrs: {},
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k] ?? null; },
    querySelector(sel) {
      if (sel === "b" || sel === "span") {
        return this.children.find((c) => c.tag === sel) || null;
      }
      if (sel === ".chev") {
        return this.children.find((c) => c.cls === "chev") || null;
      }
      return null;
    },
    appendChild(el) { this.children.push(el); return el; },
    insertBefore(el, ref) {
      const at = this.children.indexOf(ref);
      if (at === -1) {
        this.children.push(el);
      } else {
        this.children.splice(at, 0, el);
      }
      return el;
    },
    addEventListener() {},
  };
}

// Header mini button as the server renders it with no area known:
// <b>All areas</b> plus the chevron, no sub span.
function fakeMiniButton() {
  const btn = fakeEl("button");
  const pin = fakeEl("svg");
  const bold = fakeEl("b");
  bold.textContent = "All areas";
  const chev = fakeEl("svg");
  chev.cls = "chev";
  btn.appendChild(pin);
  btn.appendChild(bold);
  btn.appendChild(chev);
  return btn;
}

// Homepage hero button: one plain span.
function fakeHeroButton() {
  const btn = fakeEl("button");
  const span = fakeEl("span");
  span.textContent = "All areas";
  btn.appendChild(span);
  return btn;
}

function makeWorld({ pathname, search = "", remembered, tiles = false }) {
  const calls = [];
  const store = {};
  if (remembered !== undefined && remembered !== null) {
    store.mm_home_area = JSON.stringify(remembered);
  }
  const win = {
    location: {
      pathname, search,
      assign(url) { calls.push(url); },
    },
    localStorage: {
      getItem(k) { return k in store ? store[k] : null; },
      setItem(k, v) { store[k] = String(v); },
    },
  };
  const mini = fakeMiniButton();
  const hero = pathname === "/" ? fakeHeroButton() : null;
  const buttons = hero ? [mini, hero] : [mini];
  const tileList = tiles ? [fakeEl("button")] : [];
  const list = {
    querySelectorAll() { return tileList; },
    getAttribute() { return null; },
  };
  const pop = {
    hidden: true, dataset: {},
    querySelector(sel) {
      return sel === "[data-loc-list]" ? list : null;
    },
    querySelectorAll() { return []; },
    addEventListener() {},
    dispatchEvent() { return true; },
  };
  const doc = {
    readyState: "done",
    body: { classList: { add() {}, remove() {} } },
    getElementById(id) {
      return id === "loc-drawer" ? pop : null;
    },
    querySelector() { return null; },
    querySelectorAll(sel) {
      return sel === "[data-loc-open]" ? buttons : [];
    },
    contains() { return false; },
    createElement(tag) { return fakeEl(tag); },
    addEventListener() {},
  };
  return { win, doc, calls, store, mini, hero, pop };
}

function loadPopups(opts) {
  const world = makeWorld(opts);
  const run = new Function("window", "document", "localStorage",
    "navigator", `${POPUPS_SRC}\nreturn window.MarketPopups;`);
  world.api = run(world.win, world.doc, undefined, {});
  assert(world.api && typeof world.api.goArea === "function",
    "popups.js must expose window.MarketPopups.goArea");
  return world;
}

function loadLocate(world) {
  const run = new Function("window", "document", "localStorage",
    "navigator", `${LOCATE_SRC}\nreturn window.MarketLocate;`);
  const locate = run(world.win, world.doc, undefined, {});
  assert(locate && typeof locate.goArea === "function",
    "locate.js must expose window.MarketLocate.goArea");
  return locate;
}

// --- 1. init with a remembered area ------------------------------------

for (const pathname of ["/new", "/sellers", "/how", "/market", "/s/x",
  "/my", "/find", "/try", "/q/abc"]) {
  const world = loadPopups(
    { pathname, remembered: REMEMBERED, tiles: true });
  assert.equal(world.calls.length, 0,
    `init on ${pathname} must not navigate, got ${world.calls}`);
  assert.equal(world.pop.hidden, true,
    `drawer must not auto-open on ${pathname}`);
  assert.equal(world.mini.attrs["aria-label"], REMEMBERED,
    `header button on ${pathname} must show the remembered area`);
  assert.equal(world.mini.querySelector("b").textContent,
    "Koyambedu Market",
    `header button on ${pathname} must label the market`);
}

// Homepage: the remembered area is applied as ?area= exactly once.
{
  const world = loadPopups({ pathname: "/", remembered: REMEMBERED });
  assert.equal(world.calls.length, 1,
    `expected one navigate, got ${world.calls}`);
  assert.equal(world.calls[0],
    "/?area=" + encodeURIComponent(REMEMBERED), "homepage ?area=");
}

// Homepage with an explicit ?area=: no navigation, choice is kept.
{
  const world = loadPopups(
    { pathname: "/", search: "?area=Anna+Nagar",
      remembered: REMEMBERED });
  assert.equal(world.calls.length, 0,
    `explicit ?area= must win, got ${world.calls}`);
  assert.equal(world.store.mm_home_area, JSON.stringify("Anna Nagar"));
}

// First visit with no remembered area: Task 150 — the drawer never
// auto-opens at any width; the page defaults to All areas.
{
  const home = loadPopups({ pathname: "/", tiles: true });
  assert.equal(home.calls.length, 0, "first visit must not navigate");
  assert.equal(home.pop.hidden, true,
    "drawer must not auto-open on first homepage visit");
  const other = loadPopups({ pathname: "/new", tiles: true });
  assert.equal(other.calls.length, 0, "no bounce for first-time /new");
  assert.equal(other.pop.hidden, true,
    "drawer must not auto-open on /new");
}

// --- 2. goArea -----------------------------------------------------------

// On a shop page the pick stays on the page: stored + labelled,
// no navigation.
{
  const world = loadPopups(
    { pathname: "/s/kannan-veg", remembered: REMEMBERED });
  world.api.goArea("Anna Nagar");
  assert.equal(world.calls.length, 0,
    `goArea on a shop page must not navigate, got ${world.calls}`);
  assert.equal(world.store.mm_home_area, JSON.stringify("Anna Nagar"));
  assert.equal(world.mini.attrs["aria-label"], "Anna Nagar");
  assert.equal(world.mini.querySelector("b").textContent, "Anna Nagar");
}

// On the homepage the pick navigates to /?area=.
{
  const world = loadPopups({ pathname: "/", remembered: REMEMBERED });
  world.calls.length = 0; // ignore the init-time ?area= apply
  world.api.goArea("Anna Nagar");
  assert.deepEqual(world.calls,
    ["/?area=" + encodeURIComponent("Anna Nagar")]);
  assert.equal(world.store.mm_home_area, JSON.stringify("Anna Nagar"));
}

// On /market the pick keeps the current params and sets area.
{
  const world = loadPopups(
    { pathname: "/market", search: "?q=tomato&sort=items",
      remembered: REMEMBERED });
  world.api.goArea("Anna Nagar");
  assert.equal(world.calls.length, 1,
    `expected one navigate, got ${world.calls}`);
  const params = new URLSearchParams(world.calls[0].split("?")[1]);
  assert.equal(world.calls[0].split("?")[0], "/market");
  assert.equal(params.get("q"), "tomato");
  assert.equal(params.get("sort"), "items");
  assert.equal(params.get("area"), "Anna Nagar");
}

// --- 3. locate.js behaves the same ---------------------------------------

// With popups.js loaded, the GPS pick delegates to the shared handler.
{
  const world = loadPopups(
    { pathname: "/s/kannan-veg", remembered: REMEMBERED });
  const locate = loadLocate(world);
  locate.goArea("Anna Nagar");
  assert.equal(world.calls.length, 0,
    `GPS pick on a shop page must not navigate, got ${world.calls}`);
  assert.equal(world.store.mm_home_area, JSON.stringify("Anna Nagar"));
  assert.equal(world.mini.attrs["aria-label"], "Anna Nagar");
}

// Standalone (no popups.js): the same stay-or-go rules.
{
  const world = makeWorld(
    { pathname: "/s/kannan-veg", remembered: REMEMBERED });
  const locate = loadLocate(world);
  locate.goArea("Anna Nagar");
  assert.equal(world.calls.length, 0,
    `standalone GPS pick must not navigate, got ${world.calls}`);
  assert.equal(world.store.mm_home_area, JSON.stringify("Anna Nagar"));
  const home = makeWorld({ pathname: "/", remembered: REMEMBERED });
  loadLocate(home).goArea("Anna Nagar");
  assert.deepEqual(home.calls,
    ["/?area=" + encodeURIComponent("Anna Nagar")]);
}

console.log("remembered_area.test.mjs: ok");
