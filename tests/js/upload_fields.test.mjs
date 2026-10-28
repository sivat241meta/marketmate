// Task 56.7: upload.js must send the whole form (speak_lang), not just the file.
//
// Loads the real app/web/static/upload.js with a tiny DOM stub: a form with
// a file input plus a speak_lang select. Submit must POST all fields.
// Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SRC = fs.readFileSync(path.join(ROOT, "app/web/static/upload.js"), "utf8");

globalThis.window = { location: { href: "http://x/e/tok" } };

function makeEl(tag, opts = {}) {
  const listeners = {};
  const el = {
    tag,
    attrs: { ...(opts.attrs || {}) },
    children: [],
    hidden: !!opts.hidden,
    value: opts.value !== undefined ? opts.value : "",
    textContent: opts.text || "",
    files: opts.files || null,
    name: opts.name || "",
    dataset: { ...(opts.dataset || {}) },
    addEventListener(type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    _fire(type, event = {}) {
      for (const fn of listeners[type] || []) {
        fn({ ...event, target: el, preventDefault() {} });
      }
    },
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
  };
  return el;
}

// --- form fixture -------------------------------------------------
const fileInput = makeEl("input", { name: "video", files: [{ name: "clip.mp4", size: 1000 }] });
fileInput.attrs.type = "file";
const speakSelect = makeEl("select", { name: "speak_lang", value: "ta" });
const progressWrap = makeEl("div", { hidden: true });
const bar = makeEl("progress", {});
const meta = makeEl("p", {});
const submitBtn = makeEl("button", {});
submitBtn.attrs.type = "submit";

const formListeners = {};
const form = {
  tag: "form",
  dataset: { maxBytes: "0", uploadForm: "" },
  action: "http://x/e/tok/upload",
  _fields: [fileInput, speakSelect],
  addEventListener(type, fn) {
    (formListeners[type] = formListeners[type] || []).push(fn);
  },
  _fire(type) {
    for (const fn of formListeners[type] || []) {
      fn({ target: form, preventDefault() {} });
    }
  },
  querySelector(sel) {
    if (sel === 'input[type="file"]') {
      return fileInput;
    }
    if (sel === "[data-upload-name]") {
      return null;
    }
    if (sel === "[data-upload-file]") {
      return makeEl("p", { hidden: true });
    }
    if (sel === "[data-upload-error]") {
      return makeEl("p", { hidden: true });
    }
    if (sel === "[data-upload-progress]") {
      return progressWrap;
    }
    if (sel === "[data-upload-bar]") {
      return bar;
    }
    if (sel === "[data-upload-meta]") {
      return meta;
    }
    if (sel === "[data-upload-cancel]") {
      return null;
    }
    if (sel === '[type="submit"]') {
      return submitBtn;
    }
    return null;
  },
  querySelectorAll() {
    return [];
  },
};

const domReady = [];
globalThis.document = {
  addEventListener(type, fn) {
    if (type === "DOMContentLoaded") {
      domReady.push(fn);
    }
  },
  querySelectorAll(sel) {
    if (sel === "form[data-upload-form]") {
      return [form];
    }
    return [];
  },
};

// --- FormData + XHR stubs ------------------------------------------
const appended = [];
globalThis.FormData = class FormData {
  constructor(formEl) {
    this._form = formEl || null;
    if (formEl && formEl._fields) {
      for (const field of formEl._fields) {
        if (field.name && field !== fileInput) {
          appended.push([field.name, field.value]);
        }
      }
    }
  }

  append(name, value) {
    appended.push([name, value && value.name ? value.name : value]);
  }

  set(name, value) {
    for (let i = appended.length - 1; i >= 0; i -= 1) {
      if (appended[i][0] === name) {
        appended.splice(i, 1);
      }
    }
    this.append(name, value);
  }
};

let sentData = null;
globalThis.XMLHttpRequest = class XMLHttpRequest {
  constructor() {
    this.upload = { addEventListener() {} };
  }

  open() {}

  addEventListener() {}

  send(data) {
    sentData = data;
  }
};

new Function(SRC)();
assert.equal(domReady.length, 1, "upload.js must listen for DOMContentLoaded");
for (const fn of domReady) {
  fn();
}

// Submit with a file: must send file + speak_lang.
form._fire("submit");
assert.ok(sentData !== null, "submit must XHR-send a FormData");
const names = appended.map(([name]) => name);
assert.ok(names.includes("video"), `file field sent, got ${JSON.stringify(names)}`);
assert.ok(
  names.includes("speak_lang"),
  `speak_lang must be sent with the upload, got ${JSON.stringify(names)}`,
);
const speak = appended.find(([name]) => name === "speak_lang");
assert.equal(speak[1], "ta", "speak_lang value preserved");

console.log("upload_fields.test.mjs: ok (file + speak_lang sent)");
