// Task 68: shared rename dialog opens as a modal, traps focus, and
// closes on Esc/backdrop/Cancel with focus returned to the opener.
//
// Loads the real app/web/static/rename-dialog.js (no npm packages; a tiny
// DOM stub) and drives open/close/focus-trap/submit wiring.
// Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SRC = fs.readFileSync(
  path.join(ROOT, "app/web/static/rename-dialog.js"), "utf8");

class FakeNode {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.parentNode = null;
    this.attrs = {};
    this.listeners = {};
    this.hidden = false;
    this.className = "";
    this.textContent = "";
    this.focused = false;
    this.disabled = false;
    this.type = "";
    // selector -> element or array, consulted by query helpers.
    this.q = {};
    this.qAll = {};
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] ?? null; }
  hasAttribute(name) { return name in this.attrs; }
  removeAttribute(name) { delete this.attrs[name]; }
  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  insertBefore(child, ref) {
    child.parentNode = this;
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
    if (at !== -1) {
      this.children.splice(at, 1);
    }
    child.parentNode = null;
    return child;
  }
  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter(
      (other) => other !== fn);
  }
  dispatch(type, event) {
    (this.listeners[type] || []).forEach((fn) => fn(event));
  }
  querySelector(sel) {
    if (sel in this.q) {
      return this.q[sel];
    }
    for (const child of this.children) {
      const hit = child.querySelector(sel);
      if (hit) {
        return hit;
      }
    }
    return null;
  }
  querySelectorAll(sel) {
    if (sel in this.qAll) {
      return this.qAll[sel];
    }
    let out = [];
    for (const child of this.children) {
      out = out.concat(child.querySelectorAll(sel));
    }
    return out;
  }
  closest() { return null; }
  focus() {
    this.focused = true;
    document.activeElement = this;
  }
  submit() { this.submitted = true; }
}

function fakeEvent(key, shift) {
  return { key, shiftKey: !!shift, prevented: false,
    preventDefault() { this.prevented = true; } };
}

// Minimal document: body with classList, listener registry, one
// details[data-rename-sheet] holding a summary + form + cancel button.
const docListeners = {};
const bodyClasses = new Set();
const body = new FakeNode("body");
body.classList = {
  add(name) { bodyClasses.add(name); },
  remove(name) { bodyClasses.delete(name); },
};
const summary = new FakeNode("summary");
const form = new FakeNode("form");
form.action = "/e/TOK/item/7/name";
const title = new FakeNode("h3");
title.textContent = "Change the name";
const firstInput = new FakeNode("input");
const cancel = new FakeNode("button");
form.q = { h3: title, 'input[name="name_local"]': firstInput };
const details = new FakeNode("details");
details.appendChild(summary);
details.appendChild(form);
const document = {
  readyState: "complete",
  activeElement: null,
  body,
  createElement(tag) { return new FakeNode(tag); },
  createComment() { return new FakeNode("#comment"); },
  addEventListener(type, fn) {
    (docListeners[type] = docListeners[type] || []).push(fn);
  },
  removeEventListener(type, fn) {
    docListeners[type] = (docListeners[type] || []).filter(
      (other) => other !== fn);
  },
  querySelectorAll(sel) {
    if (sel === "details[data-rename-sheet]") {
      return [details];
    }
    return [];
  },
};
details.q = {
  "summary[data-rename-open]": summary,
  "[data-rename-cancel]": cancel,
  "[data-rename-form]": form,
  "form[data-rename-form]": form,
};
form.q["[data-rename-error]"] = null;

const fakeWindow = { location: "" };
const load = new Function(
  "window", "document", "fetch", "FormData",
  `${SRC}\nreturn window.MMRenameDialog;`);
const dialog = load(fakeWindow, document, undefined, undefined);
assert(dialog && typeof dialog.open === "function", "missing dialog API");

// Seller wiring ran at load: summary click opens the modal with the form.
assert.equal((summary.listeners.click || []).length, 1,
  "summary has no opener");
const openerEvent = fakeEvent("click");
summary.dispatch("click", openerEvent);
assert(openerEvent.prevented, "summary click must not toggle <details>");
assert(dialog.isOpen(), "dialog did not open");
assert.equal(form.hidden, false);
assert(firstInput.focused, "first field not focused");
assert(bodyClasses.has("rdlg-open"), "body scroll not locked");
const wrap = body.children[body.children.length - 1];
assert.equal(wrap.className, "rdlg-wrap");
const box = wrap.children[1];
assert.equal(box.className, "rdlg");
assert.equal(box.getAttribute("role"), "dialog");
assert.equal(box.getAttribute("aria-modal"), "true");
assert.equal(box.getAttribute("aria-label"), "Change the name");
assert(form.parentNode === box, "form not moved into the dialog");

// Escape closes, restores the form, returns focus to the opener.
const esc = fakeEvent("Escape");
(docListeners.keydown || []).forEach((fn) => fn(esc));
assert(esc.prevented, "Escape not handled");
assert(!dialog.isOpen(), "dialog did not close");
assert.equal(form.hidden, true);
assert(form.parentNode === details, "form not restored");
assert(summary.focused, "focus not returned to the opener");
assert(!bodyClasses.has("rdlg-open"), "body scroll still locked");

// Focus trap cycles inside the dialog.
const opener = new FakeNode("button");
const host = new FakeNode("div");
const sheet = new FakeNode("div");
host.appendChild(sheet);
const inputA = new FakeNode("input");
const inputB = new FakeNode("button");
sheet.q = { h3: title, 'input[name="name_local"]': inputA };
dialog.open(sheet, opener);
const trapBox = body.children[body.children.length - 1].children[1];
trapBox.qAll = { ["button, [href], input, select, textarea," +
  '[tabindex]:not([tabindex="-1"])']: [inputA, inputB] };
document.activeElement = inputB;
const tab = fakeEvent("Tab");
(docListeners.keydown || []).forEach((fn) => fn(tab));
assert(tab.prevented && inputA.focused, "Tab did not wrap to first");
inputA.focused = false;
document.activeElement = inputA;
const backTab = fakeEvent("Tab", true);
(docListeners.keydown || []).forEach((fn) => fn(backTab));
assert(backTab.prevented && inputB.focused, "Shift+Tab did not wrap");
assert(dialog.close(), "close failed");
assert(opener.focused, "focus not returned after trap test");

// Backdrop click closes too.
dialog.open(sheet, opener);
const wrap2 = body.children[body.children.length - 1];
wrap2.children[0].dispatch("click", fakeEvent("click"));
assert(!dialog.isOpen(), "backdrop click did not close");

// Cancel button closes the seller dialog.
summary.dispatch("click", fakeEvent("click"));
assert(dialog.isOpen(), "reopen failed");
cancel.dispatch("click", fakeEvent("click"));
assert(!dialog.isOpen(), "cancel did not close");

// Submit posts JSON and lands back with the renamed notice.
let posted = null;
const fakeWindow2 = { location: "" };
const fakeFetch = (url, opts) => {
  posted = { url, opts };
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ ok: true }),
  });
};
const dialog2 = new Function(
  "window", "document", "fetch", "FormData",
  `${SRC}\nreturn window.MMRenameDialog;`)(
    fakeWindow2, { ...document, readyState: "complete",
      querySelectorAll: () => [] }, fakeFetch, function () {});
dialog2.submitRename(form);
setTimeout(() => {
  assert(posted, "submit did not fetch");
  assert.equal(posted.url, "/e/TOK/item/7/name");
  assert.equal(posted.opts.method, "POST");
  assert.equal(posted.opts.headers.Accept, "application/json");
  assert.equal(fakeWindow2.location, "/e/TOK?renamed=1");
  console.log("rename_dialog.test.mjs: ok");
}, 50);
