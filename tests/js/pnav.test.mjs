// Task 149: priority+ nav moves the rightmost links into More, one at
// a time, until the header row fits — and moves them back when the
// window grows. Loads the real app/web/static/pnav.js (no npm packages;
// a tiny hand-written DOM stub) and drives fitNav with scripted link
// widths. Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SRC = fs.readFileSync(path.join(ROOT, "app/web/static/pnav.js"), "utf8");

// pnav.js returns early with no document; stub just enough for load.
globalThis.window = {};
globalThis.document = undefined;
new Function(`${SRC}`)();
const api = globalThis.window.MarketPNav;
assert(api && typeof api.fitNav === "function", "missing MarketPNav.fitNav");

// --- tiny DOM stub: only what fitNav touches -------------------------------

class List {
  constructor(items = []) {
    this.items = items;
  }
  get length() {
    return this.items.length;
  }
}

class El {
  constructor(tag, opts = {}) {
    this.tagName = String(tag).toUpperCase();
    this.attrs = new Set(opts.attrs || []);
    this.classes = new Set(opts.classes || []);
    this.children = [];
    this.parent = null;
    this.hidden = false;
    this.width = opts.width || 0;
    this.expanded = "false";
    this.classList = {
      contains: (c) => this.classes.has(c),
      toggle: (c, force) => {
        if (force === undefined) {
          if (this.classes.has(c)) this.classes.delete(c);
          else this.classes.add(c);
        } else if (force) this.classes.add(c);
        else this.classes.delete(c);
      },
      remove: (c) => this.classes.delete(c),
    };
  }
  hasAttribute(name) {
    return this.attrs.has(name);
  }
  setAttribute(name, value) {
    if (name === "aria-expanded") this.expanded = value;
  }
  get firstChild() {
    return this.children.length ? this.children[0] : null;
  }
  appendChild(node) {
    return this.insertBefore(node, null);
  }
  insertBefore(node, ref) {
    if (node.parent) {
      const at = node.parent.children.indexOf(node);
      if (at !== -1) node.parent.children.splice(at, 1);
    }
    node.parent = this;
    if (ref === null || ref === undefined) this.children.push(node);
    else this.children.splice(this.children.indexOf(ref), 0, node);
    return node;
  }
  querySelector(sel) {
    const m = /^\[([a-z-]+)\]$/.exec(sel.trim());
    assert.ok(m, `unsupported selector: ${sel}`);
    const stack = [...this.children];
    while (stack.length) {
      const el = stack.shift();
      if (el.attrs.has(m[1])) return el;
      stack.push(...el.children);
    }
    return null;
  }
  closest(sel) {
    const cls = sel.trim().replace(/^\./, "");
    let el = this;
    while (el) {
      if (el.classes.has(cls)) return el;
      el = el.parent;
    }
    return null;
  }
}

// A header row whose scrollWidth follows its visible children: fixed
// chrome (brand/location/actions) plus visible nav links, plus the
// More button only while it stands unhidden.
function makeRow({ linkWidths, chrome, moreWidth, clientWidth }) {
  const row = new El("div", { classes: ["topbar-in"] });
  row.clientWidthValue = clientWidth;
  row.chrome = chrome;
  Object.defineProperty(row, "clientWidth", {
    get() { return this.clientWidthValue; },
  });
  Object.defineProperty(row, "scrollWidth", {
    get() {
      let total = this.chrome;
      const nav = this.nav;
      for (const child of nav.children) {
        if (child.tagName === "A") total += child.width;
      }
      const more = nav.querySelector("[data-nav-more]");
      if (more && !more.hidden) total += moreWidth;
      return total;
    },
  });
  const nav = new El("nav", { attrs: ["data-pnav"] });
  nav.offsetParent = row;
  row.appendChild(nav);
  row.nav = nav;
  const links = linkWidths.map((w, i) => {
    const a = new El("a", { attrs: ["data-nav"], width: w });
    a.label = `link${i + 1}`;
    nav.appendChild(a);
    return a;
  });
  const more = new El("span", { attrs: ["data-nav-more"] });
  more.hidden = true;
  const btn = new El("button", { attrs: ["data-nav-more-btn"] });
  const menu = new El("span", { attrs: ["data-nav-more-menu"] });
  const list = new El("span", { attrs: ["data-nav-more-list"] });
  menu.appendChild(list);
  more.appendChild(btn);
  more.appendChild(menu);
  nav.appendChild(more);
  return { row, nav, links, more, list, btn };
}

function visibleLabels(nav) {
  return nav.children.filter((c) => c.tagName === "A").map((c) => c.label);
}
function listedLabels(list) {
  return list.children.map((c) => c.label);
}

// 1. Everything fits: nothing moves, More stays hidden.
{
  const t = makeRow({ linkWidths: [100, 100, 100, 100, 100], chrome: 500,
    moreWidth: 90, clientWidth: 1100 });
  assert.equal(api.fitNav(t.nav), 0);
  assert.equal(t.more.hidden, true);
  assert.deepEqual(visibleLabels(t.nav),
    ["link1", "link2", "link3", "link4", "link5"]);
}

// 2. Slight overflow: exactly the rightmost link moves, order kept.
{
  const t = makeRow({ linkWidths: [100, 100, 100, 100, 100], chrome: 500,
    moreWidth: 90, clientWidth: 990 });
  assert.equal(api.fitNav(t.nav), 1);
  assert.equal(t.more.hidden, false);
  assert.deepEqual(visibleLabels(t.nav), ["link1", "link2", "link3", "link4"]);
  assert.deepEqual(listedLabels(t.list), ["link5"]);
}

// 3. Deep overflow: links move one at a time until it fits.
{
  const t = makeRow({ linkWidths: [150, 150, 150, 200, 230], chrome: 640,
    moreWidth: 90, clientWidth: 1170 });
  // All five = 1520; four + More = 1380; three + More = 1180;
  // two + More = 1030 fits.
  assert.equal(api.fitNav(t.nav), 3);
  assert.deepEqual(visibleLabels(t.nav), ["link1", "link2"]);
  assert.deepEqual(listedLabels(t.list), ["link3", "link4", "link5"]);
}

// 4. The active underline parks under More when its link moves away.
{
  const t = makeRow({ linkWidths: [100, 100, 100, 100, 100], chrome: 500,
    moreWidth: 90, clientWidth: 990 });
  t.links[4].classes.add("is-active");
  api.fitNav(t.nav);
  assert.equal(t.btn.classes.has("is-active"), true);
  t.links[4].classes.delete("is-active");
  t.links[0].classes.add("is-active");
  api.fitNav(t.nav);
  assert.equal(t.btn.classes.has("is-active"), false);
}

// 5. Growing the window moves links back out; More hides when empty.
{
  const t = makeRow({ linkWidths: [100, 100, 100, 100, 100], chrome: 500,
    moreWidth: 90, clientWidth: 800 });
  assert.equal(api.fitNav(t.nav), 3);
  t.row.clientWidthValue = 1200;
  assert.equal(api.fitNav(t.nav), 0);
  assert.equal(t.more.hidden, true);
  assert.equal(t.btn.expanded, "false");
  assert.deepEqual(visibleLabels(t.nav),
    ["link1", "link2", "link3", "link4", "link5"]);
}

// 6. Worst case: every link moves before giving up, never looping.
{
  const t = makeRow({ linkWidths: [300, 300, 300, 300, 300], chrome: 900,
    moreWidth: 90, clientWidth: 500 });
  assert.equal(api.fitNav(t.nav), 5);
  assert.equal(t.more.hidden, false);
  assert.deepEqual(listedLabels(t.list),
    ["link1", "link2", "link3", "link4", "link5"]);
}

// 7. A hidden nav (phone widths: the sheet owns the links) is skipped.
{
  const t = makeRow({ linkWidths: [300, 300, 300, 300, 300], chrome: 900,
    moreWidth: 90, clientWidth: 500 });
  t.nav.offsetParent = null;
  assert.equal(api.fitNav(t.nav), 0);
  assert.equal(t.more.hidden, true);
}

console.log("pnav.test.mjs: ok");
