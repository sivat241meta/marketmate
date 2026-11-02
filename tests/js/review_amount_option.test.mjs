// Task 160: QTY_WORD_MISMATCH options read "¼ kg" / "1 kg" but the
// per-amount input needs the plain number. Loads the real review.js
// (no npm packages) and checks parseAmountOption resolves each form.
// Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SRC = fs.readFileSync(path.join(ROOT, "app/web/static/review.js"), "utf8");

globalThis.document = {
  addEventListener() {},
  querySelector() { return null; },
  getElementById() { return null; },
};
globalThis.window = {};
const { parseAmountOption } = new Function(`${SRC}\nreturn { parseAmountOption };`)();

assert.equal(parseAmountOption("¼ kg"), "0.25");
assert.equal(parseAmountOption("½ kg"), "0.5");
assert.equal(parseAmountOption("¾ kg"), "0.75");
assert.equal(parseAmountOption("1 kg"), "1");
assert.equal(parseAmountOption("250 g"), "250");
assert.equal(parseAmountOption("0.5"), "0.5");
assert.equal(parseAmountOption("6"), "6");
assert.equal(parseAmountOption("Remove"), null);

console.log("amount option parsing ok");
