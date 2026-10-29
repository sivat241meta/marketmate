// Task 60: the seller alert banner shows only when latest_id grew.
//
// Loads the real app/web/static/order-alert.js and drives its exported
// shouldAlert(prevId, nextId) decision: a larger latest_id (or a first id
// after none) alerts; same, smaller, or missing ids stay quiet.
// Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SRC = fs.readFileSync(
  path.join(ROOT, "app/web/static/order-alert.js"), "utf8");

const module = { exports: {} };
const loader = new Function("module", "exports", "window", "document",
  "navigator", "localStorage", SRC);
loader(module, module.exports, undefined, undefined, undefined, undefined);

const shouldAlert = module.exports.shouldAlert;
assert.equal(typeof shouldAlert, "function",
  "order-alert.js must export shouldAlert");

// Growth alerts.
assert.equal(shouldAlert(11, 12), true, "12 after 11 alerts");
assert.equal(shouldAlert(null, 12), true, "first id after none alerts");
assert.equal(shouldAlert(0, 5), true, "5 after 0 alerts");

// Quiet cases.
assert.equal(shouldAlert(12, 12), false, "same id stays quiet");
assert.equal(shouldAlert(12, 11), false, "smaller id stays quiet");
assert.equal(shouldAlert(12, null), false, "cleared orders stay quiet");
assert.equal(shouldAlert(null, null), false, "none twice stays quiet");

console.log("order_alert.test.mjs: ok");
