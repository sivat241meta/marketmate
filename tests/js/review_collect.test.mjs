// Task 45: collectCards must ignore a carried box instead of throwing.
//
// Loads the real collectCards from app/web/static/review.js (no npm packages;
// a tiny hand-written DOM stub) and feeds it a form with one real price card
// plus a carried box shaped like the crashing template: no data-card and an
// h2 without .name-local/.name-en spans (the exact real-browser TypeError).
// Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SRC = fs.readFileSync(path.join(ROOT, "app/web/static/review.js"), "utf8");

// review.js runs document.addEventListener at load; stub just enough for load.
globalThis.document = { addEventListener() {}, querySelector() { return null; } };
globalThis.window = {};
const { collectCards } = new Function(`${SRC}\nreturn { collectCards };`)();

// --- tiny DOM stub: only what collectCards touches ---------------------------

function dataKey(attr) {
  return attr.slice("data-".length).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
}

function parseSimple(sel) {
  const m = /^([a-zA-Z][a-zA-Z0-9]*)?((?:\.[A-Za-z0-9_-]+)*)((?:\[[^\]]+\])*)$/
    .exec(sel.trim());
  assert.ok(m, `unsupported selector: ${sel}`);
  const classes = (m[2].match(/\.[A-Za-z0-9_-]+/g) || []).map((c) => c.slice(1));
  const attrs = [];
  for (const part of m[3].match(/\[[^\]]+\]/g) || []) {
    const am = /^\[([A-Za-z0-9_-]+)(?:="([^"]*)")?\]$/.exec(part);
    assert.ok(am, `unsupported attribute selector: ${part}`);
    attrs.push({ name: am[1], value: am[2] });
  }
  return { tag: (m[1] || "").toLowerCase(), classes, attrs };
}

function matches(el, simple) {
  if (simple.tag && el.tag !== simple.tag) {
    return false;
  }
  for (const c of simple.classes) {
    if (!el.classes.has(c)) {
      return false;
    }
  }
  for (const a of simple.attrs) {
    const key = a.name.startsWith("data-") ? dataKey(a.name) : a.name;
    const has = key in el.dataset;
    if (a.value === undefined) {
      if (!has) {
        return false;
      }
    } else if (!has || String(el.dataset[key]) !== a.value) {
      return false;
    }
  }
  return true;
}

class El {
  constructor(tag, opts = {}, children = []) {
    this.tag = String(tag).toLowerCase();
    this.classes = new Set(opts.classes || []);
    this.dataset = { ...(opts.dataset || {}) };
    this.textContent = opts.text || "";
    this.value = opts.value !== undefined ? opts.value : "";
    this.checked = !!opts.checked;
    this.children = children;
  }

  *walk() {
    for (const child of this.children) {
      yield child;
      yield* child.walk();
    }
  }

  querySelectorAll(selector) {
    const simples = String(selector).split(",").map(parseSimple);
    const out = [];
    for (const el of this.walk()) {
      if (simples.some((s) => matches(el, s))) {
        out.push(el);
      }
    }
    return out;
  }

  querySelector(selector) {
    const all = this.querySelectorAll(selector);
    return all.length ? all[0] : null;
  }
}

// --- fixture -----------------------------------------------------------------

const form = new El("form", {}, [
  new El("section", { classes: ["card", "review-card"], dataset: { card: "0" } }, [
    new El("h2", {}, [
      new El("span", { classes: ["name-local"], text: "தக்காளி " }),
      new El("span", { classes: ["name-en"], text: " tomato" }),
    ]),
    new El("input", { dataset: { item: "0", line: "0", field: "price" }, value: "20" }),
    new El("input", { dataset: { item: "0", line: "0", field: "per_amount" }, value: "1" }),
    new El("select", { dataset: { item: "0", line: "0", field: "unit" }, value: "kg" }),
    new El("input", { dataset: { item: "0", field: "qty" }, value: "" }),
    new El("input", { dataset: { cardConfirm: "", item: "0" }, checked: true }),
    new El("script", {
      classes: ["proof-data"],
      dataset: { item: "0" },
      text: JSON.stringify({ quote: "q", turn_ids: [], start_ms: 0, end_ms: 0 }),
    }),
  ]),
  // Carried box as rendered by the crashing template: no data-card, and an
  // h2 with no name spans (collectCards must skip it, but still read its
  // checked carried ids for the approve POST body).
  new El("section", { classes: ["card"] }, [
    new El("h2", { text: "Also on your list (not in this session)" }),
    new El("input", { dataset: { carried: "", id: "5" }, checked: true }),
    new El("input", { dataset: { carried: "", id: "7" }, checked: false }),
  ]),
  // Stray card section with data-card but no h2 at all: skip, don't throw.
  new El("section", { classes: ["card"], dataset: { card: "9" } }, []),
]);

// --- assertions ---------------------------------------------------------------

let result;
assert.doesNotThrow(() => {
  result = collectCards(form);
}, "collectCards threw on a form with a carried box");
assert.equal(result.items.length, 1);
assert.equal(result.items[0].name_en, "tomato");
assert.equal(result.items[0].name_local, "தக்காளி");
assert.equal(result.items[0].price_lines[0].price, 20);
assert.equal(result.items[0].price_lines[0].unit, "kg");
assert.deepEqual(result.confirmed, [0]);
assert.deepEqual(result.carried, [5]);

console.log("review_collect.test.mjs: ok (carried box ignored, ids kept)");
