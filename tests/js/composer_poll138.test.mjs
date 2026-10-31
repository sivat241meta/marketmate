// Task 138: the upload bubble waits up to 8 minutes with real step labels,
// and never shows "Done" before the server says done. Unit-tests the pure
// helpers exposed as initComposer.testHooks: pollDelay, pollElapsedMs,
// activeStepLabel and bubbleSteps. Exit 0 on success, non-zero on failure.

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
const { pollDelay, pollElapsedMs, activeStepLabel, bubbleSteps } = hooks;
const BUDGET = hooks.POLL_BUDGET_MS;

// --- 1. the poll budget is >= 8 minutes -------------------------------------
assert.ok(typeof BUDGET === "number", "POLL_BUDGET_MS exposed");
assert.ok(BUDGET >= 8 * 60 * 1000, `budget ${BUDGET}ms >= 8 min`);

// --- 2. gentle back-off: 2 s at first, up to 5 s -----------------------------
assert.equal(pollDelay(0), 2000);
assert.ok(pollDelay(1) > pollDelay(0), "back-off grows");
for (let n = 0; n < 200; n++) {
  assert.ok(pollDelay(n) <= 5000, `pollDelay(${n}) capped at 5s`);
  assert.ok(pollDelay(n + 1) >= pollDelay(n), `pollDelay(${n}) monotonic`);
}
assert.equal(pollDelay(100000), 5000);

// --- 3. elapsed time crosses the budget (the give-up condition) --------------
assert.equal(pollElapsedMs(0), 0);
assert.equal(pollElapsedMs(1), 2000);
assert.ok(pollElapsedMs(50) < BUDGET, "a 106 s video (~50 polls) keeps going");
assert.ok(pollElapsedMs(10000) >= BUDGET, "the poll eventually gives up");

// --- 4. the step label comes from the active step -----------------------------
const steps = [
  { key: "listening", label: "Listening", state: "done" },
  { key: "photos", label: "Picking a photo for each item",
    state: "active" },
  { key: "ready", label: "Ready", state: "todo" },
];
assert.equal(activeStepLabel({ steps }), "Picking a photo for each item");
assert.equal(activeStepLabel({ steps: [] }), "");
assert.equal(activeStepLabel({}), "");
assert.equal(activeStepLabel(null), "");
assert.equal(activeStepLabel({ steps: [{ key: "x", state: "done" }] }), "");
// First active step wins; entries without labels are skipped.
assert.equal(activeStepLabel({ steps: [
  { key: "a", state: "active" },
  { key: "b", label: "Second", state: "active" },
] }), "Second");

// --- 5. only the current step plus finished ones — no early "Done" ------------
const labels = ["Sending…", "Listening…", "Understanding…", "Done"];
assert.deepEqual(bubbleSteps(0, labels),
  [{ label: "Sending…", state: "active" }]);
assert.deepEqual(bubbleSteps(1, labels), [
  { label: "Sending…", state: "done" },
  { label: "Listening…", state: "active" },
]);
assert.deepEqual(bubbleSteps(2, labels), [
  { label: "Sending…", state: "done" },
  { label: "Listening…", state: "done" },
  { label: "Understanding…", state: "active" },
]);
for (const active of [0, 1, 2]) {
  const shown = bubbleSteps(active, labels).map((row) => row.label);
  assert.ok(!shown.includes("Done"), `no Done at step ${active}`);
}
assert.deepEqual(bubbleSteps(3, labels)[3],
  { label: "Done", state: "active" });

console.log("composer_poll138.test.mjs: ok");
