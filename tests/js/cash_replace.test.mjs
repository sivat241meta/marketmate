// Task 101: the "Customer gave" field ships pre-filled with the bill total.
// Focusing it must select the whole value so typing replaces it (typing
// 200 on a 140 total gives "200", not "140200"), and the first on-screen
// keypad press must replace the untouched prefill too. Chips keep working.
//
// Loads the real app/web/static/cash.js (no npm packages; a tiny
// hand-written DOM stub). Exit 0 on success, non-zero on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SRC = fs.readFileSync(path.join(ROOT, "app/web/static/cash.js"), "utf8");

function matches(el, sel) {
  const m = /^\[([A-Za-z0-9_-]+)(="([^"]*)")?\]$/.exec(sel.trim());
  if (!m) {
    return false;
  }
  const value = Object.hasOwn(el.attrs, m[1]) ? el.attrs[m[1]] : null;
  if (value === null) {
    return false;
  }
  return m[2] === undefined || value === m[3];
}

function makeEl(tag, attrs = {}) {
  const listeners = {};
  const el = {
    tag,
    attrs: { ...attrs },
    children: [],
    hidden: false,
    value: attrs.value !== undefined ? attrs.value : "",
    textContent: "",
    selectionStart: 0,
    selectionEnd: 0,
    select() {
      el.selectionStart = 0;
      el.selectionEnd = el.value.length;
    },
    addEventListener(type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    _fire(type) {
      for (const fn of listeners[type] || []) {
        fn({ target: el });
      }
    },
    getAttribute(name) {
      return Object.hasOwn(this.attrs, name) ? this.attrs[name] : null;
    },
    appendChild(child) {
      el.children.push(child);
      return child;
    },
    querySelector(sel) {
      return el.querySelectorAll(sel)[0] || null;
    },
    querySelectorAll(sel) {
      const out = [];
      for (const child of el.children) {
        if (matches(child, sel)) {
          out.push(child);
        }
        out.push(...child.querySelectorAll(sel));
      }
      return out;
    },
  };
  return el;
}

function makeBox(total) {
  const box = makeEl("div", { "data-cash": "", "data-total": String(total) });
  const input = makeEl("input", { "data-cash-gave": "", value: String(total) });
  const back = makeEl("b", { "data-cash-back": "" });
  box.appendChild(input);
  box.appendChild(back);
  const chips = {};
  for (const kind of ["50", "100", "200", "500", "exact"]) {
    const chip = makeEl("button", { "data-cash-chip": kind });
    box.appendChild(chip);
    chips[kind] = chip;
  }
  const keys = makeEl("div", { "data-cash-keys": "" });
  const buttons = {};
  for (const key of ["1", "2", "3", "4", "5", "6", "7", "8", "9",
                     "clear", "0", "back"]) {
    const btn = makeEl("button", { "data-key": key });
    keys.appendChild(btn);
    buttons[key] = btn;
  }
  box.appendChild(keys);
  return { box, input, back, chips, buttons };
}

// type() mimics the browser: the typed char replaces the current selection.
function type(input, char) {
  const start = Math.min(input.selectionStart, input.selectionEnd);
  const end = Math.max(input.selectionStart, input.selectionEnd);
  input.value = input.value.slice(0, start) + char + input.value.slice(end);
  input.selectionStart = input.selectionEnd = start + 1;
  input._fire("input");
}

const first = makeBox(140);
const second = makeBox(140);
const third = makeBox(140);

const domReady = [];
globalThis.document = {
  addEventListener(type, fn) {
    if (type === "DOMContentLoaded") {
      domReady.push(fn);
    }
  },
  querySelectorAll(sel) {
    if (sel === "[data-cash]") {
      return [first.box, second.box, third.box];
    }
    return [];
  },
};

new Function(SRC)();
assert.equal(domReady.length, 1, "cash.js must listen for DOMContentLoaded");
for (const fn of domReady) {
  fn();
}

// Prefill equals the total: nothing to give back yet.
assert.equal(first.back.textContent, "₹0");

// Focus selects the whole pre-filled value ...
first.input._fire("focus");
assert.equal(first.input.selectionStart, 0, "selection starts at 0");
assert.equal(first.input.selectionEnd, 3, "selection covers the prefill");

// ... so typing 200 gives "200" (₹60 back), not "140200".
type(first.input, "2");
type(first.input, "0");
type(first.input, "0");
assert.equal(first.input.value, "200", "typing after focus replaces");
assert.equal(first.back.textContent, "₹60");

// First keypad press on an untouched prefill replaces it too.
second.buttons["2"]._fire("click");
assert.equal(second.input.value, "2", "first keypad press replaces");
assert.equal(second.back.textContent, "₹0");
second.buttons["0"]._fire("click");
assert.equal(second.input.value, "20", "later presses append");

// Back on an untouched prefill clears it, like deleting selected text.
third.buttons.back._fire("click");
assert.equal(third.input.value, "");
assert.equal(third.back.textContent, "₹0");

// Chips keep working: fixed amounts and exact total.
first.chips["200"]._fire("click");
assert.equal(first.input.value, "200");
assert.equal(first.back.textContent, "₹60");
first.chips.exact._fire("click");
assert.equal(first.input.value, "140");
assert.equal(first.back.textContent, "₹0");
first.chips["500"]._fire("click");
assert.equal(first.back.textContent, "₹360");

console.log("cash_replace.test.mjs: focus selects, typing/keypad replace, chips work");
