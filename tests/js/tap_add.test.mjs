// Task 52.1: the new-bill "Add" button must set the first quantity.
//
// Loads the real app/web/static/tap-chips.js (no npm packages; a tiny
// hand-written DOM stub) and drives one fake tap-form line: Add must set
// qty to 1 (the selected size chip when one exists, else 1 unit), reveal
// the stepper, and fire input/change so quote.js refreshes the receipt and
// float bar. Setting qty back to 0 must bring Add back.
// Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SRC = fs.readFileSync(path.join(ROOT, "app/web/static/tap-chips.js"), "utf8");

globalThis.window = {};
globalThis.Event = class Event {
  constructor(type, opts = {}) {
    this.type = type;
    this.bubbles = !!opts.bubbles;
  }
};

function matches(el, sel) {
  sel = sel.trim();
  if (sel.includes(" ")) {
    return false; // no descendant trees inside a line in this stub
  }
  const tagMatch = /^[a-zA-Z][a-zA-Z0-9]*/.exec(sel);
  let rest = sel;
  if (tagMatch && !sel.startsWith("[")) {
    if (el.tag !== tagMatch[0].toLowerCase()) {
      return false;
    }
    rest = sel.slice(tagMatch[0].length);
  }
  const attrRe = /\[([A-Za-z0-9_-]+)(\^?=("[^"]*"))?\]/g;
  let m;
  let seen = false;
  while ((m = attrRe.exec(rest)) !== null) {
    seen = true;
    const value = Object.hasOwn(el.attrs, m[1]) ? el.attrs[m[1]] : null;
    if (value === null) {
      return false;
    }
    if (m[2]) {
      const want = m[3].slice(1, -1);
      if (m[2][0] === "^") {
        if (!value.startsWith(want)) {
          return false;
        }
      } else if (value !== want) {
        return false;
      }
    }
  }
  return seen;
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
    classList: { add() {}, remove() {}, toggle() {} },
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
    dispatchEvent(event) {
      el._fire(event.type);
      return true;
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
    closest() {
      return null;
    },
  };
  return el;
}

function makeLine(unit) {
  const line = makeEl("article", { "data-line": "" });
  const add = makeEl("button", { "data-add": "" });
  add.hidden = true; // template ships Add hidden; init flips it for qty 0
  const stepper = makeEl("span", { "data-stepper": "" });
  const dec = makeEl("button", { "data-step": "-1" });
  const inc = makeEl("button", { "data-step": "1" });
  stepper.appendChild(dec);
  stepper.appendChild(inc);
  const qty = makeEl("input", { name: "qty_0", value: "0", type: "number" });
  stepper.appendChild(qty);
  const unitInput = makeEl("input", { name: "unit_0", value: unit, type: "hidden" });
  const amountInput = makeEl("input", { name: "amount_0", value: "", type: "hidden" });
  line.appendChild(add);
  line.appendChild(stepper);
  line.appendChild(unitInput);
  line.appendChild(amountInput);
  return { line, add, stepper, qty, unitInput };
}

const kg = makeLine("kg");
const pc = makeLine("piece");
const lines = [kg.line, pc.line];

const domReady = [];
globalThis.document = {
  addEventListener(type, fn) {
    if (type === "DOMContentLoaded") {
      domReady.push(fn);
    }
  },
  querySelector() {
    return null; // no keypad on this page shape
  },
  querySelectorAll(sel) {
    if (sel === "[data-tap-form] [data-line]") {
      return lines;
    }
    return [];
  },
};

new Function(SRC)();
assert.equal(domReady.length, 1, "tap-chips.js must listen for DOMContentLoaded");
for (const fn of domReady) {
  fn();
}

// Init: zero-qty lines show Add and hide the stepper.
for (const part of [kg, pc]) {
  assert.equal(part.add.hidden, false, "Add visible for qty 0");
  assert.equal(part.stepper.hidden, true, "stepper hidden for qty 0");
}

// Add sets the first quantity: 1 unit (1 kg for kg items).
let changed = 0;
kg.qty.addEventListener("input", () => {
  changed += 1;
});
kg.add._fire("click");
assert.equal(kg.qty.value, "1", "Add sets qty to 1 for kg items");
assert.equal(kg.unitInput.value, "kg", "unit stays kg");
assert.equal(kg.add.hidden, true, "Add hides after tap");
assert.equal(kg.stepper.hidden, false, "stepper shows after tap");
assert.ok(changed >= 1, "Add fires input so totals refresh");

pc.add._fire("click");
assert.equal(pc.qty.value, "1", "Add sets qty to 1 for piece items");

// Minus down to 0 brings Add back (quote.js updates the input, then
// tap-chips.js sees the change event).
kg.qty.value = "0";
kg.qty._fire("input");
assert.equal(kg.add.hidden, false, "Add returns when qty reaches 0");
assert.equal(kg.stepper.hidden, true, "stepper hides when qty reaches 0");

console.log("tap_add.test.mjs: Add sets qty, totals refresh, Add returns at 0");
