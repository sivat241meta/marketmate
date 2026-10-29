// Task 84: homepage area chooser helpers.
//
// Loads the real app/web/static/home.js with no DOM (init skips itself)
// and checks the nearest-area helper plus the privacy rule: the file must
// not contain fetch/XHR/beacons, so the customer's coordinates can never
// be posted. Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SRC = fs.readFileSync(path.join(ROOT, "app/web/static/home.js"), "utf8");

assert(!SRC.includes("fetch("), "home.js must not call fetch");
assert(!SRC.includes("XMLHttpRequest"), "home.js must not use XHR");
assert(!SRC.includes("navigator.sendBeacon"), "home.js must not beacon");

const run = new Function("window", "document", "localStorage", "navigator",
  `${SRC}\nreturn window.MarketHome;`);
const api = run({}, undefined, undefined, {});
assert(api && typeof api.nearestArea === "function", "missing nearestArea");
assert(typeof api.haversineKm === "function", "missing haversineKm");

const areas = [
  { name: "Koyambedu", lat: 13.07, lng: 80.29 },
  { name: "Anna Nagar", lat: 13.09, lng: 80.21 },
];

// Next to Koyambedu market -> Koyambedu.
assert.equal(api.nearestArea(areas, 13.071, 80.291), "Koyambedu");
// Next to Anna Nagar -> Anna Nagar.
assert.equal(api.nearestArea(areas, 13.089, 80.211), "Anna Nagar");
// Tiles without coordinates are skipped, never crash.
assert.equal(api.nearestArea([{ name: "Nowhere" }], 13.07, 80.29), null);
assert.equal(api.nearestArea([], 13.07, 80.29), null);

// Same point -> zero; ~1.2 km for 0.0108 degrees of latitude.
assert.equal(api.haversineKm(13.0827, 80.2707, 13.0827, 80.2707), 0);
const d = api.haversineKm(13.0827, 80.2707, 13.0935, 80.2707);
assert(d > 1.1 && d < 1.3, `expected ~1.2 km, got ${d}`);

console.log("home_chooser.test.mjs: ok");
