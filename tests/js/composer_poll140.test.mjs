// Task 140: the upload bubble keeps polling while the server progresses.
// Unit-tests the pure helpers exposed as initComposer.testHooks:
// pollProgressKey (the progress signature: stage, active-step label with
// its "(n of m)" counter, detail, message) and pollStalled (the 3-minute
// no-change clock), plus the 20-minute total budget.
// Exit 0 on success, non-zero on failure.

import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

// --- browser stubs (same shape as composer_status.test.mjs) -----------------
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
const { pollProgressKey, pollStalled, activeStepLabel } = hooks;
const BUDGET = hooks.POLL_BUDGET_MS;
const STALL = hooks.POLL_STALL_MS;

// --- 1. budgets: 20 minutes total, 3 minutes without change ------------------
assert.equal(BUDGET, 20 * 60 * 1000, `budget ${BUDGET}ms == 20 min`);
assert.equal(STALL, 3 * 60 * 1000, `stall ${STALL}ms == 3 min`);

// --- 2. the progress key follows the photo counter ---------------------------
function photoData(n, m) {
  return {
    status: "processing",
    stage: "photos",
    detail: `item ${n} of ${m}`,
    steps: [
      { key: "items", label: "Finding the items", state: "done" },
      { key: "photos",
        label: `Picking a photo for each item (${n} of ${m})`,
        state: "active" },
      { key: "checking", label: "Checking every price", state: "todo" },
    ],
  };
}

const seventh = photoData(7, 21);
const eighth = photoData(8, 21);
assert.notEqual(pollProgressKey(seventh), pollProgressKey(eighth),
  "the key moves while the counter moves");
assert.equal(activeStepLabel(seventh),
  "Picking a photo for each item (7 of 21)",
  "the bubble keeps the real step label with its counter");

// A new stage is progress too.
const checking = {
  status: "processing",
  stage: "checking",
  detail: "",
  steps: [
    { key: "photos", label: "Picking a photo for each item", state: "done" },
    { key: "checking", label: "Checking every price", state: "active" },
  ],
};
assert.notEqual(pollProgressKey(eighth), pollProgressKey(checking),
  "the key moves when the stage moves on");

// Identical polls give identical keys, so the stall clock can run.
assert.equal(pollProgressKey(seventh), pollProgressKey(photoData(7, 21)));
assert.equal(typeof pollProgressKey({}), "string");
assert.equal(typeof pollProgressKey(null), "string");

// --- 3. the stall clock fires at exactly 3 minutes idle ----------------------
assert.equal(pollStalled(0), false);
assert.equal(pollStalled(3 * 60 * 1000 - 1), false);
assert.equal(pollStalled(3 * 60 * 1000), true);
assert.equal(pollStalled(20 * 60 * 1000), true);

console.log("composer_poll140.test.mjs: ok");
