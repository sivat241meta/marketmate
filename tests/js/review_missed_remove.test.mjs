// Task 157: a MISSED_PRICE "Remove" tap drops the whole card and the
// removed index rides along in collectCards, so the server drops the
// same stored draft.
//
// Loads the real review.js (no npm packages; a tiny hand-written DOM
// stub), wires it through the DOMContentLoaded callback, clicks the
// Remove option and checks the card is gone and approve re-enables.
// Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SRC = fs.readFileSync(path.join(ROOT, "app/web/static/review.js"), "utf8");

// Capture the DOMContentLoaded wiring; the form is installed below.
let ready = null;
const listeners = {};
globalThis.document = {
  addEventListener(type, fn) {
    if (type === "DOMContentLoaded") {
      ready = fn;
    } else {
      (listeners[type] = listeners[type] || []).push(fn);
    }
  },
  querySelector() { return null; },
  getElementById(id) {
    return id === "review-form" ? form : null;
  },
};
globalThis.window = {};
const { collectCards } = new Function(`${SRC}\nreturn { collectCards };`)();

// --- tiny DOM stub -----------------------------------------------------------

function dataKey(attr) {
  return attr.slice("data-".length).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
}

function parseSimple(sel) {
  let rest = sel.trim();
  let id = null;
  const hash = rest.indexOf("#");
  if (hash >= 0) {
    const after = rest.slice(hash + 1);
    const mId = /^[A-Za-z0-9_-]+/.exec(after);
    assert.ok(mId, `unsupported selector: ${sel}`);
    id = mId[0];
    rest = (rest.slice(0, hash) + after.slice(id.length)).trim() || "*";
  }
  const m = /^([a-zA-Z*][A-Za-z0-9]*)?((?:\.[A-Za-z0-9_-]+)*)((?:\[[^\]]+\])*)$/
    .exec(rest);
  assert.ok(m, `unsupported selector: ${sel}`);
  const classes = (m[2].match(/\.[A-Za-z0-9_-]+/g) || []).map((c) => c.slice(1));
  const attrs = [];
  for (const part of m[3].match(/\[[^\]]+\]/g) || []) {
    const am = /^\[([A-Za-z0-9_-]+)(?:="([^"]*)")?\]$/.exec(part);
    assert.ok(am, `unsupported attribute selector: ${part}`);
    attrs.push({ name: am[1], value: am[2] });
  }
  return { tag: (m[1] || "").toLowerCase(), id, classes, attrs };
}

function matches(el, simple) {
  if (simple.tag && simple.tag !== "*" && el.tag !== simple.tag) {
    return false;
  }
  if (simple.id && el.dataset.id !== simple.id && el.idAttr !== simple.id) {
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
    this.idAttr = opts.id || null;
    this.textContent = opts.text || "";
    this.value = opts.value !== undefined ? opts.value : "";
    this.checked = !!opts.checked;
    this.disabled = !!opts.disabled;
    this.hidden = !!opts.hidden;
    this.parent = null;
    this.handlers = {};
    this.children = [];
    for (const child of children) {
      this.append(child);
    }
  }

  append(child) {
    child.parent = this;
    this.children.push(child);
    return child;
  }

  remove() {
    if (this.parent) {
      const at = this.parent.children.indexOf(this);
      if (at >= 0) {
        this.parent.children.splice(at, 1);
      }
      this.parent = null;
    }
  }

  closest(selector) {
    const simple = parseSimple(selector);
    let node = this;
    while (node) {
      if (matches(node, simple)) {
        return node;
      }
      node = node.parent;
    }
    return null;
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

  addEventListener(type, fn) {
    (this.handlers[type] = this.handlers[type] || []).push(fn);
  }

  click() {
    for (const fn of this.handlers.click || []) {
      fn({ preventDefault() {} });
    }
  }
}

// --- fixture: one clean card plus one MISSED_PRICE card ----------------------

function priceInputs(item, price, per, unit) {
  return [
    new El("input", { dataset: { item, line: "0", field: "price" }, value: price }),
    new El("input", { dataset: { item, line: "0", field: "per_amount" }, value: per }),
    new El("select", { dataset: { item, line: "0", field: "unit" }, value: unit }),
    new El("input", { dataset: { item, field: "qty" }, value: "" }),
  ];
}

const approveBtn = new El("button", { id: "approve-btn", disabled: true });
const approveError = new El("p", { id: "approve-error", hidden: true });

const card0 = new El("section", { classes: ["card"], dataset: { card: "0" } }, [
  new El("h2", {}, [
    new El("span", { classes: ["name-local"], text: "பீன்ஸ்" }),
    new El("span", { classes: ["name-en"], text: "beans" }),
  ]),
  ...priceInputs("0", "35", "0.25", "kg"),
  new El("input", { dataset: { cardConfirm: "", item: "0" }, checked: true }),
  new El("script", {
    classes: ["proof-data"],
    dataset: { item: "0" },
    text: JSON.stringify({ quote: "q0", turn_ids: [2], start_ms: 0, end_ms: 1 }),
  }),
]);

const removeBtn = new El("button", {
  classes: ["opt-btn"],
  dataset: { item: "1", flag: "MISSED_PRICE", targetField: "name", value: "Remove" },
  text: "✕ Remove",
});
const beansBtn = new El("button", {
  classes: ["opt-btn"],
  dataset: { item: "1", flag: "MISSED_PRICE", targetField: "name", value: "beans" },
  text: "beans",
});
const card1 = new El("section", { classes: ["card"], dataset: { card: "1" } }, [
  new El("h2", {}, [
    new El("span", { classes: ["name-local"], text: "" }),
    new El("span", { classes: ["name-en"], text: "other" }),
  ]),
  new El("div", { classes: ["flag-options"], dataset: { flag: "MISSED_PRICE", item: "1" } }, [
    new El("div", { classes: ["choice"] }, [beansBtn, removeBtn]),
  ]),
  ...priceInputs("1", "70", "1", "kg"),
  new El("input", { dataset: { cardConfirm: "", item: "1" }, checked: false }),
  new El("script", {
    classes: ["proof-data"],
    dataset: { item: "1" },
    text: JSON.stringify({ quote: "q1", turn_ids: [3], start_ms: 0, end_ms: 1 }),
  }),
]);

const form = new El("form", {
  id: "review-form",
  dataset: {
    approveUrl: "/approve",
    msgReady: "ready",
    msgNeedOne: "1 item still needs your choice or a tick",
    msgNeedMany: "{n} items still need your choice or a tick",
    msgCounts: "{ok} of {total} look right",
    msgCountsAria: "{ok} of {total} prices look right",
    msgApproveFailed: "Approve failed.",
  },
}, [approveBtn, approveError, card0, card1]);

// --- assertions ---------------------------------------------------------------

assert.ok(ready, "DOMContentLoaded wiring was not registered");
ready();
assert.equal(approveBtn.disabled, true, "approve starts disabled with a MISSED card");

let before = collectCards(form);
assert.equal(before.items.length, 2);
assert.deepEqual(before.removed, []);

removeBtn.click();

assert.equal(form.dataset.removed, "[1]");
assert.equal(form.querySelectorAll(".card[data-card]").length, 1);
const after = collectCards(form);
assert.equal(after.items.length, 1);
assert.equal(after.items[0].name_en, "beans");
assert.deepEqual(after.removed, [1]);
assert.deepEqual(after.confirmed, [0]);
assert.equal(approveBtn.disabled, false, "approve re-enables once the card is gone");

removeBtn.click();
assert.equal(form.dataset.removed, "[1]", "removal is idempotent");

console.log("review_missed_remove.test.mjs: ok (Remove drops the card, index rides along)");
