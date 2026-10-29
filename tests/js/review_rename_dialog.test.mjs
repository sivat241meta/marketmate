// Task 99: check-page rename must save while the sheet sits in the dialog.
//
// Loads the real app/web/static/rename-dialog.js + review.js (no npm
// packages; a tiny hand-written DOM stub) and drives the real-browser flow:
// open the rename dialog, type new names, Save. The dialog moves the sheet
// out of the card, so saveRename must find the card by data-item, not by
// DOM ancestry; close must put the sheet back into the card.
// Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const RENAME_SRC = fs.readFileSync(
  path.join(ROOT, "app/web/static/rename-dialog.js"), "utf8");
const REVIEW_SRC = fs.readFileSync(
  path.join(ROOT, "app/web/static/review.js"), "utf8");

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
    let has;
    let value;
    if (a.name.startsWith("data-")) {
      const key = dataKey(a.name);
      has = key in el.dataset;
      value = el.dataset[key];
    } else {
      has = Object.hasOwn(el.attrs, a.name);
      value = el.attrs[a.name];
    }
    if (a.value === undefined) {
      if (!has) {
        return false;
      }
    } else if (!has || String(value) !== a.value) {
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
    this.type = opts.type || "";
    this.children = [];
    this.parent = null;
    this.listeners = {};
    for (const child of children) {
      this.appendChild(child);
    }
  }

  get parentNode() {
    return this.parent;
  }

  get nextSibling() {
    if (!this.parent) {
      return null;
    }
    const at = this.parent.children.indexOf(this);
    return this.parent.children[at + 1] || null;
  }

  get className() {
    return [...this.classes].join(" ");
  }

  set className(value) {
    this.classes = new Set(
      String(value).split(/\s+/).filter(Boolean));
  }

  _adopt(child) {
    if (child.parent) {
      const at = child.parent.children.indexOf(child);
      if (at >= 0) {
        child.parent.children.splice(at, 1);
      }
    }
    child.parent = this;
  }

  appendChild(child) {
    this._adopt(child);
    this.children.push(child);
    return child;
  }

  insertBefore(child, ref) {
    this._adopt(child);
    const at = ref ? this.children.indexOf(ref) : -1;
    if (at === -1) {
      this.children.push(child);
    } else {
      this.children.splice(at, 0, child);
    }
    return child;
  }

  removeChild(child) {
    const at = this.children.indexOf(child);
    if (at >= 0) {
      this.children.splice(at, 1);
    }
    child.parent = null;
    return child;
  }

  remove() {
    if (this.parent) {
      this.parent.removeChild(this);
    }
  }

  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }

  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter(
      (other) => other !== fn);
  }

  _fire(type, event) {
    for (const fn of this.listeners[type] || []) {
      fn(event || { preventDefault() {} });
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

  setAttribute(name, value) {
    this.attrs[name] = String(value);
    if (name.startsWith("data-")) {
      this.dataset[dataKey(name)] = String(value);
    }
  }

  getAttribute(name) {
    return Object.hasOwn(this.attrs, name) ? this.attrs[name] : null;
  }

  removeAttribute(name) {
    delete this.attrs[name];
    if (name.startsWith("data-")) {
      delete this.dataset[dataKey(name)];
    }
  }

  focus() {
    globalThis.document.activeElement = this;
  }
}

// --- fixture: one needs-decision card shaped like review.html ---------------
const OLD_LOCAL = "தக்காளி";
const OLD_EN = "tomato";
const NEW_LOCAL = "கத்தரி";
const NEW_EN = "brinjal";
const NEW_VARIETY = "green long";

const headLocal = new El("span", { classes: ["name-local"], text: OLD_LOCAL });
const headEn = new El("span", { classes: ["name-en"], text: OLD_EN });
const head = new El("h2", {}, [headLocal, headEn]);
const openBtn = new El("button",
  { classes: ["pen-icon"], dataset: { renameOpen: "", item: "0" } });
const mark = new El("span",
  { classes: ["chip", "c-need"], dataset: { renamedMark: "" }, hidden: true });
const inputLocal = new El("input",
  { attrs: { name: "name_local" }, value: OLD_LOCAL });
const inputEn = new El("input",
  { attrs: { name: "name_en" }, value: OLD_EN });
const inputVariety = new El("input",
  { attrs: { name: "variety" }, value: "" });
const cancelBtn = new El("button", { dataset: { renameCancel: "" } });
const saveBtn = new El("button", { dataset: { renameSave: "" } });
const sheet = new El("div",
  {
    classes: ["rename-sheet"],
    dataset: { renameForm: "", item: "0" },
    hidden: true,
  },
  [
    new El("h3", { text: "Change the name" }),
    inputLocal, inputEn, inputVariety,
    new El("div", { classes: ["rename-actions"] }, [cancelBtn, saveBtn]),
  ]);
const card = new El("section",
  {
    classes: ["card", "review-card", "needs", "form-card"],
    dataset: { card: "0", needs: "1", variety: "" },
  },
  [
    head, openBtn, mark, sheet,
    new El("div", { classes: ["line"] }, [
      new El("input", {
        dataset: { item: "0", line: "0", field: "price", original: "20" },
        value: "20",
      }),
      new El("input", {
        dataset: { item: "0", line: "0", field: "per_amount", original: "1" },
        value: "1",
      }),
      new El("select", {
        dataset: { item: "0", line: "0", field: "unit", original: "kg" },
        value: "kg",
      }),
    ]),
    new El("input", {
      dataset: { item: "0", field: "qty", original: "" }, value: "",
    }),
  ]);
const approveBtn = new El("button", { id: "approve-btn", disabled: true });
const approveErr = new El("p", { id: "approve-error", hidden: true });
const form = new El("form", { id: "review-form" },
  [card, approveBtn, approveErr]);
form.dataset.approveUrl = "/approve";
form.dataset.msgNeedOne = "1 item still needs your choice or a tick";
form.dataset.msgNeedMany = "{n} items still need your choice or a tick";
form.dataset.msgCounts = "{ok}/{total} ready, {need} need you";
form.dataset.msgCountsAria = "{ok} of {total} ready";
form.dataset.msgReady = "All cards look right — ready to approve.";
form.dataset.msgPlayConfirm = "Play the clip, then tick I confirm.";
form.dataset.msgApproveFailed = "Approve failed.";

const homeIndex = card.children.indexOf(sheet);
assert.ok(homeIndex >= 0, "fixture: sheet starts inside the card");

const docListeners = {};
const body = new El("body");
body.classList = {
  add(name) { body.classes.add(name); },
  remove(name) { body.classes.delete(name); },
};
globalThis.window = {};
globalThis.document = {
  readyState: "complete",
  activeElement: null,
  body,
  createElement(tag) { return new El(tag); },
  createComment() { return new El("comment"); },
  addEventListener(type, fn) {
    (docListeners[type] = docListeners[type] || []).push(fn);
  },
  removeEventListener(type, fn) {
    docListeners[type] = (docListeners[type] || []).filter(
      (other) => other !== fn);
  },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  getElementById(id) {
    if (id === "review-form") {
      return form;
    }
    return null;
  },
};

new Function(RENAME_SRC)();
const dialog = globalThis.window.MMRenameDialog;
assert(dialog && typeof dialog.open === "function", "missing dialog API");
const { collectCards } = new Function(`${REVIEW_SRC}\nreturn { collectCards };`)();
for (const fn of docListeners.DOMContentLoaded || []) {
  fn();
}
assert.equal(approveBtn.disabled, false, "wiring did not run");

// --- open: the sheet leaves the card for the dialog -------------------------
openBtn._fire("click");
assert(dialog.isOpen(), "dialog did not open");
assert.equal(sheet.hidden, false, "sheet not shown in the dialog");
assert.equal(sheet.parentNode.className, "rdlg",
  "sheet not moved into the dialog box");
assert.equal(sheet.closest(".card"), null,
  "sheet must be outside the card while the dialog is open");
assert.equal(card.querySelector("[data-rename-form]"), null,
  "card must not contain the sheet while the dialog is open");
assert.equal(inputLocal.value, OLD_LOCAL, "local field not prefilled");
assert.equal(inputEn.value, OLD_EN, "en field not prefilled");

// --- type + save: the card headline updates ----------------------------------
inputLocal.value = NEW_LOCAL;
inputEn.value = NEW_EN;
inputVariety.value = NEW_VARIETY;
saveBtn._fire("click");
assert(!dialog.isOpen(), "dialog did not close on save");
assert.equal(headLocal.textContent, NEW_LOCAL, "card kept the old local name");
assert.equal(headEn.textContent, NEW_EN, "card kept the old en name");
const varietyLine = card.querySelector("[data-variety-line]");
assert(varietyLine, "variety line not created");
assert.equal(varietyLine.textContent, NEW_VARIETY, "variety not saved");
assert.equal(card.dataset.renamed, "1", "card not marked renamed");
assert.equal(mark.hidden, false, "edited mark not shown");

// --- the sheet returns into its original place in the card ------------------
assert.equal(sheet.hidden, true, "sheet not hidden after save");
assert.equal(sheet.parentNode, card, "sheet not restored into the card");
assert.equal(card.children.indexOf(sheet), card.children.indexOf(mark) + 1,
  "sheet not restored to its original place");
assert.equal(card.querySelector("[data-rename-form]"), sheet,
  "card lost its rename sheet after close");

// --- the approve payload carries the new names ------------------------------
const payload = collectCards(form);
assert.equal(payload.items.length, 1, "expected one payload item");
assert.equal(payload.items[0].name_local, NEW_LOCAL, "payload local stale");
assert.equal(payload.items[0].name_en, NEW_EN, "payload en stale");
assert.equal(payload.items[0].variety, NEW_VARIETY, "payload variety stale");
assert.equal(payload.items[0].price_lines[0].price, 20, "price lines changed");

// --- cancel restores the sheet without touching the headline ----------------
openBtn._fire("click");
assert(dialog.isOpen(), "reopen failed");
inputLocal.value = "abandoned";
cancelBtn._fire("click");
assert(!dialog.isOpen(), "cancel did not close the dialog");
assert.equal(sheet.parentNode, card, "cancel did not restore the sheet");
assert.equal(card.children.indexOf(sheet), card.children.indexOf(mark) + 1,
  "cancel misplaced the sheet");
assert.equal(headLocal.textContent, NEW_LOCAL, "cancel changed the headline");

// --- Esc restores the sheet too ----------------------------------------------
openBtn._fire("click");
assert(dialog.isOpen(), "second reopen failed");
const esc = { key: "Escape", prevented: false, preventDefault() { this.prevented = true; } };
for (const fn of docListeners.keydown || []) {
  fn(esc);
}
assert(esc.prevented, "Escape not handled");
assert(!dialog.isOpen(), "Escape did not close the dialog");
assert.equal(sheet.parentNode, card, "Escape did not restore the sheet");
assert.equal(card.children.indexOf(sheet), card.children.indexOf(mark) + 1,
  "Escape misplaced the sheet");
assert.equal(headLocal.textContent, NEW_LOCAL, "Escape changed the headline");

console.log("review_rename_dialog.test.mjs: ok (dialog save updates card + payload, sheet restored)");
