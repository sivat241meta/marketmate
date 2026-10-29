// Task 63: on-device haversine distance for Market "Near me".
//
// Loads the real app/web/static/near-me.js with no DOM (init skips itself)
// and checks the distance helper plus the privacy rule: the file must not
// contain fetch/XHR, so the customer's coordinates can never be posted.
// Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SRC = fs.readFileSync(path.join(ROOT, "app/web/static/near-me.js"), "utf8");

assert(!SRC.includes("fetch("), "near-me.js must not call fetch");
assert(!SRC.includes("XMLHttpRequest"), "near-me.js must not use XHR");
assert(!SRC.includes("navigator.sendBeacon"), "near-me.js must not beacon");

const run = new Function("globalThis", `${SRC}\nreturn globalThis.MarketNearMe;`);
const api = run(globalThis);
assert(api && typeof api.haversineKm === "function", "missing haversineKm");

// Same point -> zero.
assert.equal(api.haversineKm(13.0827, 80.2707, 13.0827, 80.2707), 0);

// ~1.2 km apart in Chennai (13.0827,80.2707 -> 13.0935,80.2707 ~= 1.2 km).
const d = api.haversineKm(13.0827, 80.2707, 13.0935, 80.2707);
assert(d > 1.1 && d < 1.3, `expected ~1.2 km, got ${d}`);

// Symmetry + formatting.
assert.equal(api.haversineKm(13.0935, 80.2707, 13.0827, 80.2707), d);
assert.equal(api.formatKm(1.234), "1.2 km");
assert.equal(api.formatKm(12.6), "13 km");

console.log("near_me.test.mjs: ok");
