// Task 143: QTY_AS_PRICE / MULTI_PRICE_UNCLEAR options keep one line.
//
// Loads the real parseLineOption / keepOptionLine / isSelfConfirmFlag from
// app/web/static/review.js (no npm packages; a tiny hand-rolled card stub)
// and checks that tapping "Rs.20 for 5 pieces" keeps that line and drops
// the "Rs.5 / 1 kg" line, and that the choice self-confirms like TWO_PRICES.
// Exit 0 on success, non-zero with a message on failure.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SRC = fs.readFileSync(path.join(ROOT, "app/web/static/review.js"), "utf8");

// review.js runs document.addEventListener at load; stub just enough for load.
globalThis.document = { addEventListener() {}, querySelector() { return null; } };
globalThis.window = {};
const { parseLineOption, keepOptionLine, isSelfConfirmFlag, isLineChoiceFlag } =
  new Function(
    `${SRC}\nreturn { parseLineOption, keepOptionLine, isSelfConfirmFlag, isLineChoiceFlag };`,
  )();

// --- parseLineOption ---------------------------------------------------------

assert.deepEqual(parseLineOption("₹20 for 5 pieces"),
  { price: "20", per: "5", unit: "piece", perImplied: false });
assert.deepEqual(parseLineOption("₹5 per kg"),
  { price: "5", per: "1", unit: "kg", perImplied: true });
assert.deepEqual(parseLineOption("₹100 per dozen"),
  { price: "100", per: "1", unit: "dozen", perImplied: true });
assert.deepEqual(parseLineOption("₹35 for 2 bunches"),
  { price: "35", per: "2", unit: "bunch", perImplied: false });
assert.equal(parseLineOption("20"), null);
assert.equal(parseLineOption(""), null);
assert.equal(parseLineOption(null), null);

// --- keepOptionLine ----------------------------------------------------------

function fakeLine(price, per, unit) {
  const fields = {
    price: { value: String(price) },
    per_amount: { value: String(per) },
    unit: { value: String(unit) },
  };
  return {
    fields,
    removed: false,
    querySelector(sel) {
      const m = /data-field="([^"]+)"/.exec(sel);
      return m ? fields[m[1]] || null : null;
    },
    remove() {
      this.removed = true;
    },
  };
}

function fakeCard(specs) {
  const card = {
    lines: specs.map(([p, a, u]) => fakeLine(p, a, u)),
    querySelectorAll(sel) {
      assert.equal(sel, ".line");
      return card.lines.filter((line) => !line.removed);
    },
  };
  return card;
}

function keptSpecs(card) {
  return card.querySelectorAll(".line").map((line) => [
    line.fields.price.value,
    line.fields.per_amount.value,
    line.fields.unit.value,
  ]);
}

let card = fakeCard([["5", "1", "kg"], ["20", "5", "piece"]]);
keepOptionLine(card, "₹20 for 5 pieces");
assert.deepEqual(keptSpecs(card), [["20", "5", "piece"]]);

card = fakeCard([["5", "1", "kg"], ["20", "5", "piece"]]);
keepOptionLine(card, "₹5 per kg");
assert.deepEqual(keptSpecs(card), [["5", "1", "kg"]]);

// Unknown option text never drops a line.
card = fakeCard([["5", "1", "kg"], ["20", "5", "piece"]]);
keepOptionLine(card, "20");
assert.deepEqual(keptSpecs(card), [["5", "1", "kg"], ["20", "5", "piece"]]);

// "per kg" also matches a blank per-amount.
card = fakeCard([["5", "", "kg"], ["20", "5", "piece"]]);
keepOptionLine(card, "₹5 per kg");
assert.deepEqual(keptSpecs(card), [["5", "", "kg"]]);

// --- self-confirm ------------------------------------------------------------

assert.equal(isLineChoiceFlag("QTY_AS_PRICE"), true);
assert.equal(isLineChoiceFlag("MULTI_PRICE_UNCLEAR"), true);
assert.equal(isLineChoiceFlag("TWO_PRICES"), true);
assert.equal(isLineChoiceFlag("SOUND_ALIKE"), false);
assert.equal(isSelfConfirmFlag("QTY_AS_PRICE"), true);
assert.equal(isSelfConfirmFlag("MULTI_PRICE_UNCLEAR"), true);
assert.equal(isSelfConfirmFlag("TWO_PRICES"), true);
assert.equal(isSelfConfirmFlag("SOUND_ALIKE"), true);
assert.equal(isSelfConfirmFlag("JUMP"), false);

console.log("review_line_choice143: ok");
