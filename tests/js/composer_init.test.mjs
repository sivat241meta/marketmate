// Task 123: composer.js exposes exactly one global (initComposer) and wires a
// composer root (dropdown menu, unhidden mic/plus, hidden no-JS fallback).
// Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

function makeEl(extra = {}) {
  const listeners = {};
  return {
    hidden: false,
    disabled: false,
    required: false,
    value: "",
    textContent: "",
    dataset: {},
    style: {},
    children: [],
    classList: {
      added: [],
      add(name) {
        this.added.push(name);
      },
      toggle() {},
    },
    setAttribute() {},
    addEventListener(type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
    focus() {},
    ...extra,
  };
}

// --- browser stubs --------------------------------------------------
globalThis.window = {
  location: { href: "http://x/" },
  setTimeout: (fn) => 0,
};
const windowKeysBefore = new Set(Object.keys(globalThis.window));
globalThis.document = {
  readyState: "complete",
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener: () => {},
  createElement: () => makeEl(),
};
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};

await import(pathToFileURL(path.join(ROOT, "app/web/static/composer.js")).href);

const win = globalThis.window;
const added = Object.keys(win).filter((k) => !windowKeysBefore.has(k));
assert.deepEqual(added, ["initComposer"]);
assert.equal(typeof win.initComposer, "function");

// --- fake composer root ----------------------------------------------
const nojs = makeEl({ hidden: false });
const menu = makeEl({ hidden: false });
const plus = makeEl({ hidden: true });
const mic = makeEl({ hidden: true });
const send = makeEl({ hidden: true });
const cancel = makeEl({ hidden: true });
const textarea = makeEl({ value: "" });
const fileInput = makeEl({ disabled: true, required: true });
const videoLabel = makeEl({ hidden: true });
const videoInput = makeEl({ disabled: true });
const form = makeEl({
  action: "http://x/s/shop/quote",
  checkValidity: () => true,
  reportValidity: () => {},
});
form.querySelectorAll = () => [];

const bySelector = {
  "[data-composer-form]": form,
  "[data-composer-thread]": makeEl(),
  "[data-composer-pill]": makeEl(),
  "[data-composer-plus]": plus,
  "[data-composer-menu]": menu,
  "[data-composer-text]": textarea,
  "[data-composer-wave]": makeEl(),
  "[data-composer-timer]": makeEl(),
  "[data-composer-mic]": mic,
  "[data-composer-send]": send,
  "[data-composer-cancel]": cancel,
  "[data-composer-hint]": makeEl(),
  "[data-composer-live]": makeEl(),
  "[data-composer-nojs]": nojs,
};
const root = makeEl({
  dataset: {
    field: "audio",
    textField: "items",
    maxSeconds: "120",
    doneLabel: "Review order",
    strRecording: "Recording…",
  },
});
root.querySelector = (sel) => bySelector[sel] || null;
root.querySelectorAll = (sel) => {
  if (sel === "[data-composer-file]") {
    return [fileInput, videoInput];
  }
  if (sel === "[data-composer-video-only]") {
    return [videoLabel];
  }
  return [];
};

win.initComposer(root);

assert.ok(root.classList.added.includes("is-js"), "is-js class added");
assert.equal(nojs.hidden, true, "no-JS fallback hidden");
assert.equal(menu.hidden, true, "menu becomes a dropdown");
assert.equal(plus.hidden, false, "+ button shown");
assert.equal(mic.hidden, false, "mic shown");
assert.equal(send.hidden, true, "send hidden until text");
assert.equal(cancel.hidden, true, "cancel hidden until recording");
assert.equal(fileInput.disabled, false, "upload enabled");
assert.equal(fileInput.required, false, "upload not required for fetch sends");
assert.equal(videoLabel.hidden, false, "video menu items shown");
assert.equal(root.dataset.state, "idle");

// Second init is a no-op.
root.classList.added.length = 0;
win.initComposer(root);
assert.deepEqual(root.classList.added, []);

console.log("composer_init.test.mjs: ok");
