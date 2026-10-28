// Task 56.1: edited-card confirm must stick; SOUND_ALIKE/TWO_PRICES option is confirmation.
//
// Loads the real app/web/static/review.js (no npm packages; a tiny DOM stub)
// and drives: (a) tick on an edited card stays ticked and enables Approve;
// (b) picking a SOUND_ALIKE option needs no extra tick; (c) edit note only
// shows when a field really differs.
// Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SRC = fs.readFileSync(path.join(ROOT, "app/web/static/review.js"), "utf8");

globalThis.window = { location: "" };
globalThis.Event = class Event {
  constructor(type, opts = {}) {
    this.type = type;
    this.bubbles = !!opts.bubbles;
  }
};

function dataKey(attr) {
  return attr.slice("data-".length).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
}

function parseSimple(sel) {
  sel = sel.trim();
  if (sel.startsWith("#")) {
    return { id: sel.slice(1) };
  }
  const m = /^([a-zA-Z][a-zA-Z0-9]*)?((?:\.[A-Za-z0-9_-]+)*)((?:\[[^\]]+\])*)$/
    .exec(sel);
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
  if (simple.id) {
    return el.attrs.id === simple.id;
  }
  if (simple.tag && el.tag !== simple.tag) {
    return false;
  }
  for (const c of simple.classes || []) {
    if (!el.classes.has(c)) {
      return false;
    }
  }
  for (const a of simple.attrs || []) {
    if (a.name === "hidden") {
      if (!el.hidden) {
        return false;
      }
      continue;
    }
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
    this.attrs = { ...(opts.attrs || {}) };
    if (opts.id) {
      this.attrs.id = opts.id;
    }
    this.classes = new Set(opts.classes || []);
    this.dataset = { ...(opts.dataset || {}) };
    this.textContent = opts.text || "";
    this.value = opts.value !== undefined ? opts.value : "";
    this.checked = !!opts.checked;
    this.hidden = !!opts.hidden;
    this.disabled = !!opts.disabled;
    this.children = [];
    this.parent = null;
    this.listeners = {};
    for (const child of children) {
      this.appendChild(child);
    }
    const self = this;
    this.classList = {
      add(...names) {
        for (const n of names) {
          self.classes.add(n);
        }
      },
      remove(...names) {
        for (const n of names) {
          self.classes.delete(n);
        }
      },
      toggle(name) {
        if (self.classes.has(name)) {
          self.classes.delete(name);
        } else {
          self.classes.add(name);
        }
      },
      contains(name) {
        return self.classes.has(name);
      },
    };
  }

  appendChild(child) {
    child.parent = this;
    this.children.push(child);
    return child;
  }

  remove() {
    if (!this.parent) {
      return;
    }
    const idx = this.parent.children.indexOf(this);
    if (idx >= 0) {
      this.parent.children.splice(idx, 1);
    }
    this.parent = null;
  }

  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }

  _fire(type, target) {
    for (const fn of this.listeners[type] || []) {
      fn({ target: target || this, preventDefault() {} });
    }
    if (this.parent && type !== "click") {
      // bubble input/change/submit to form listeners
      this.parent._fire(type, target || this);
    }
  }

  dispatchEvent(event) {
    this._fire(event.type, this);
    return true;
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

  setAttribute(name, value) {
    this.attrs[name] = String(value);
  }

  getAttribute(name) {
    return Object.hasOwn(this.attrs, name) ? this.attrs[name] : null;
  }
}

// --- fixture: card 0 edited (price 20 -> 25), visible confirm; card 1
// SOUND_ALIKE options [13,30] with price 13, visible confirm ---------------
function priceLine(item, line, price, per, unit) {
  return new El("div", { classes: ["line"] }, [
    new El("input", {
      dataset: { item: String(item), line: String(line), field: "price", original: price },
      value: price,
    }),
    new El("input", {
      dataset: { item: String(item), line: String(line), field: "per_amount", original: per },
      value: per,
    }),
    new El("select", {
      dataset: { item: String(item), line: String(line), field: "unit", original: unit },
      value: unit,
    }),
  ]);
}

const price0 = priceLine(0, 0, "20", "1", "kg");
// seller edits price 20 -> 25
price0.children[0].value = "25";

const note0 = new El("p", { dataset: { editNote: "" }, hidden: true });
const box0 = new El("input", { dataset: { cardConfirm: "", item: "0" }, checked: false });
const wrap0 = new El("div", { dataset: { confirmWrap: "" }, hidden: false }, [note0, box0]);
const card0 = new El(
  "section",
  { classes: ["card"], dataset: { card: "0" } },
  [price0, wrap0],
);

const price1 = priceLine(1, 0, "13", "1", "kg");
const opt13 = new El("button", {
  classes: ["opt-btn"],
  dataset: { item: "1", flag: "SOUND_ALIKE", targetField: "price", value: "13" },
});
const opt30 = new El("button", {
  classes: ["opt-btn"],
  dataset: { item: "1", flag: "SOUND_ALIKE", targetField: "price", value: "30" },
});
const group1 = new El(
  "div",
  { classes: ["flag-options"], dataset: { flag: "SOUND_ALIKE", item: "1" } },
  [opt13, opt30],
);
const note1 = new El("p", { dataset: { editNote: "" }, hidden: true });
const box1 = new El("input", { dataset: { cardConfirm: "", item: "1" }, checked: false });
const wrap1 = new El("div", { dataset: { confirmWrap: "" }, hidden: false }, [note1, box1]);
const card1 = new El(
  "section",
  { classes: ["card"], dataset: { card: "1" } },
  [group1, price1, wrap1],
);

const approveBtn = new El("button", { id: "approve-btn", attrs: {}, disabled: true });
const approveErr = new El("p", { id: "approve-error", attrs: {}, hidden: true });
const approveCount = new El("p", { dataset: { approveCount: "" } });

const form = new El("form", { id: "review-form" }, [
  card0,
  card1,
  approveBtn,
  approveErr,
  approveCount,
]);
form.dataset.approveUrl = "/approve";
form.dataset.msgNeedOne = "1 item still needs your choice or a tick";
form.dataset.msgNeedMany = "{n} items still need your choice or a tick";
form.dataset.msgCounts = "{ok}/{total} ready, {need} need you";
form.dataset.msgCountsAria = "{ok} of {total} ready";
form.dataset.msgReady = "All cards look right — ready to approve.";
form.dataset.msgPlayConfirm = "Play the clip, then tick I confirm.";
form.dataset.msgApproveFailed = "Approve failed.";

const domReady = [];
globalThis.document = {
  addEventListener(type, fn) {
    if (type === "DOMContentLoaded") {
      domReady.push(fn);
    }
  },
  querySelector() {
    return null;
  },
  querySelectorAll() {
    return [];
  },
  getElementById(id) {
    if (id === "review-form") {
      return form;
    }
    return null;
  },
};

new Function(SRC)();
assert.equal(domReady.length, 1, "review.js must listen for DOMContentLoaded");
for (const fn of domReady) {
  fn();
}

// Initial: both cards need a tick/choice, Approve disabled.
assert.equal(approveBtn.disabled, true, "Approve starts disabled");

// (a) editing shows the note; the tick on the edited card must stick.
const priceInput0 = price0.children[0];
priceInput0._fire("input", priceInput0);
assert.equal(note0.hidden, false, "edited card shows the changed-note");
box0.checked = true;
box0._fire("change", box0);
box0._fire("input", box0);
assert.equal(box0.checked, true, "confirm tick on edited card must not untick itself");
assert.equal(note0.hidden, false, "tick keeps the changed-note visible");

// Card 1 still needs a choice, so Approve stays disabled.
assert.equal(approveBtn.disabled, true, "Approve waits for card 1 choice");

// (b) picking a SOUND_ALIKE option IS the confirmation.
opt30._fire("click");
assert.ok(opt30.classes.has("chosen"), "picked option gets .chosen");
assert.equal(
  box1.checked,
  true,
  "SOUND_ALIKE choice auto-confirms (no extra tick needed)",
);
assert.equal(note1.hidden, true, "option choice is not a manual edit: note stays hidden");
assert.equal(approveBtn.disabled, false, "Approve enables after tick + option choice");

// (c) a later manual edit clears the tick again.
const priceInput1 = price1.children[0];
priceInput1.value = "31";
priceInput1._fire("input", priceInput1);
assert.equal(box1.checked, false, "later price edit clears the tick");
assert.equal(note1.hidden, false, "manual edit shows the changed-note");
assert.equal(approveBtn.disabled, true, "Approve disables until re-ticked");

// Reverting to the heard value hides the note.
priceInput1.value = "30";
priceInput1.dataset.original = "30";
priceInput1._fire("input", priceInput1);
// After revert there is no manual diff; re-tick to finish.
box1.checked = true;
box1._fire("change", box1);
assert.equal(box1.checked, true, "re-tick sticks after revert");
assert.equal(approveBtn.disabled, false, "Approve enables after re-tick");

console.log("review_confirm_tick.test.mjs: ok (tick sticks, option confirms, note gated)");
