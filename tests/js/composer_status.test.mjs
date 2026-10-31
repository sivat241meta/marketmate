// Task 131: composer status polling never hangs and never fakes "Done".
// Unit-tests the pure helpers exposed as initComposer.testHooks:
// statusView (poll read), stepForStage, isDoneData, isNeedsAction,
// languagePostUrl, collectFields (speak_lang inclusion) and fileTooBig.
// Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

// --- browser stubs (same shape as composer_init.test.mjs) -----------------
globalThis.window = {
  location: { href: "http://x/" },
  setTimeout: (fn) => 0,
};
globalThis.document = {
  readyState: "complete",
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener: () => {},
  createElement: () => ({}),
};

await import(pathToFileURL(path.join(ROOT, "app/web/static/composer.js")).href);

const hooks = globalThis.window.initComposer.testHooks;
assert.ok(hooks, "testHooks exposed");
const { statusView, stepForStage, isDoneData, isNeedsAction,
  languagePostUrl, collectFields, fileTooBig } = hooks;

// --- 1. language_check (and any needs-action flag) stops the poll ---------
assert.deepEqual(
  statusView({ status: "processing", stage: "language_check",
    message: "We heard Kannada letters, but this video was set to English. Pick the language you spoke." }),
  { kind: "needs_action", step: 1 });
assert.equal(isNeedsAction({ status: "processing", stage: "language_check" }),
  true);
assert.equal(isNeedsAction({ status: "processing", stage: "listening",
  needs_action: true }), true);
assert.equal(isNeedsAction({ status: "processing", stage: "listening" }),
  false);

// --- 2. "Done" only for done statuses --------------------------------------
for (const status of ["review", "approved", "done", "complete",
    "completed"]) {
  assert.deepEqual(statusView({ status, stage: "ready" }),
    { kind: "done", step: 3 }, status);
  assert.equal(isDoneData({ status }), true, status);
}
// The page's own done marker (a created bill/quote) also counts.
assert.equal(isDoneData({ status: "processing", bill_id: 7 }), true);
assert.equal(isDoneData({ status: "processing", quote_token: "abc" }), true);
// Everything still working is pending — never done.
for (const status of ["uploaded", "processing", ""]) {
  for (const stage of ["uploaded", "listening", "items", "matching",
      "checking", "ready", "photos", ""]) {
    const view = statusView({ status, stage });
    assert.equal(view.kind, "pending", `${status}/${stage}`);
    assert.ok(view.step === 1 || view.step === 2, `${status}/${stage}`);
  }
  assert.equal(isDoneData({ status }), false, status);
}
// failed stays failed.
assert.deepEqual(statusView({ status: "failed", stage: "ready" }),
  { kind: "failed", step: 1 });
assert.deepEqual(statusView({ status: "error" }), { kind: "failed", step: 1 });

// --- 3. steps follow the real stage ----------------------------------------
assert.equal(stepForStage("listening"), 1);
assert.equal(stepForStage("uploaded"), 1);
assert.equal(stepForStage("looking"), 1);
assert.equal(stepForStage("transcribing"), 1);
assert.equal(stepForStage("matching"), 2);
assert.equal(stepForStage("items"), 2);
assert.equal(stepForStage("checking"), 2);
assert.equal(stepForStage("ready"), 2);
assert.equal(stepForStage(""), 1);

// --- 4. language POST url derives from the status url -----------------------
assert.equal(languagePostUrl("/e/abc/s/5/status"), "/e/abc/s/5/language");
assert.equal(languagePostUrl("/e/abc/s/5/status/"), "/e/abc/s/5/language");
assert.equal(languagePostUrl("/e/abc/s/5"), "");
assert.equal(languagePostUrl(""), "");
assert.equal(languagePostUrl(null), "");

// --- 5. FormData includes speak_lang ----------------------------------------
const pairs = [];
const fakeForm = { append: (k, v) => pairs.push([k, v]) };
const ctx = {
  form: {
    querySelectorAll: () => [
      { disabled: false, name: "speak_lang", type: "hidden",
        value: "ta" },
      { disabled: false, name: "customer_name", type: "text",
        value: "Meena" },
      // Skipped: unchecked boxes, files, disabled controls, the textarea.
      { disabled: false, name: "ok", type: "checkbox", checked: false,
        value: "1" },
      { disabled: false, name: "audio", type: "file", value: "" },
      { disabled: true, name: "nope", type: "text", value: "x" },
    ],
  },
  textarea: null,
  textField: "",
};
collectFields(ctx, fakeForm);
assert.deepEqual(pairs, [["speak_lang", "ta"], ["customer_name", "Meena"]]);

// --- 6. too-big files are blocked client-side --------------------------------
assert.equal(fileTooBig({ maxBytes: 100 }, { size: 101 }), true);
assert.equal(fileTooBig({ maxBytes: 100 }, { size: 100 }), false);
assert.equal(fileTooBig({ maxBytes: 0 }, { size: 10 ** 9 }), false);
assert.equal(fileTooBig({ maxBytes: 100 }, null), false);

console.log("composer_status.test.mjs: ok");
