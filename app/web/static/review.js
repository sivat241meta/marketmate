"use strict";
/* Review cards: one-tap option buttons fill the first price input of the
   card; approve posts the edited cards as JSON. */

function cardInputs(form, index) {
  return Array.from(
    form.querySelectorAll(`[data-item="${index}"][data-field]`));
}

function collectCards(form) {
  const proofs = {};
  form.querySelectorAll(".proof-data").forEach((node) => {
    proofs[node.dataset.item] = JSON.parse(node.textContent);
  });
  const names = {};
  form.querySelectorAll(".card").forEach((card) => {
    const head = card.querySelector("h2");
    names[card.dataset.card] = {
      ta: head.querySelector("[lang=ta]").textContent.trim(),
      en: head.querySelector(".name-en").textContent.trim(),
    };
  });
  const byItem = {};
  form.querySelectorAll("[data-item][data-field]").forEach((input) => {
    const item = input.dataset.item;
    byItem[item] = byItem[item] || { lines: {}, qty: null };
    if (input.dataset.field === "qty") {
      byItem[item].qty = input.value === "" ? null : Number(input.value);
    } else {
      const line = input.dataset.line;
      byItem[item].lines[line] = byItem[item].lines[line] || {};
      byItem[item].lines[line][input.dataset.field] =
        input.value === "" ? null
        : (input.dataset.field === "unit" ? input.value : Number(input.value));
    }
  });
  const confirmed = [];
  const items = Object.keys(byItem).sort().map((key, position) => {
    const entry = byItem[key];
    const lines = Object.keys(entry.lines).sort().map((line) => entry.lines[line]);
    const box = form.querySelector(`[data-confirm][data-item="${key}"]`);
    if (box && box.checked) {
      confirmed.push(position);
    }
    const proof = proofs[key] || {};
    return {
      name_spoken: names[key] ? names[key].en : "",
      name_ta: names[key] ? names[key].ta : "",
      name_en: names[key] ? names[key].en : "",
      variety: null,
      price_lines: lines.map((line) => ({
        said: "", price: line.price ?? null,
        per_amount: line.per_amount ?? null, unit: line.unit ?? null,
      })),
      range_said: false,
      qty: entry.qty, qty_unit: null,
      proof: {
        quote: proof.quote || "", turn_ids: proof.turn_ids || [],
        start_ms: proof.start_ms || 0, end_ms: proof.end_ms || 0,
        frame: proof.frame || null, audio_clip: proof.audio_clip || null,
      },
      flags: [], photo: null, condition_hint: null, confirmed: false,
    };
  });
  return { items, confirmed };
}

function updateApprove(form) {
  const button = form.querySelector("#approve-btn");
  const error = form.querySelector("#approve-error");
  let unresolved = 0;
  form.querySelectorAll(".flag-options, .flag-blocking").forEach((flag) => {
    const box = flag.querySelector("[data-confirm]");
    if (box && !box.checked) {
      unresolved += 1;
    }
  });
  button.disabled = unresolved > 0;
  if (error) {
    error.hidden = unresolved === 0;
    if (unresolved > 0) {
      error.textContent = `${unresolved} flag(s) still need a choice or a confirm tick.`;
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("review-form");
  if (!form) {
    return;
  }
  form.querySelectorAll(".opt-btn").forEach((button) => {
    button.addEventListener("click", () => {
      const input = form.querySelector(
        `[data-item="${button.dataset.item}"][data-field="price"]`);
      if (input) {
        input.value = button.dataset.value;
      }
      updateApprove(form);
    });
  });
  form.addEventListener("input", () => updateApprove(form));
  form.addEventListener("change", () => updateApprove(form));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const response = await fetch(form.dataset.approveUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectCards(form)),
    });
    if (response.redirected || response.ok) {
      window.location = response.url;
    } else {
      const error = form.querySelector("#approve-error");
      const detail = await response.json().catch(() => ({}));
      if (error) {
        error.hidden = false;
        error.textContent = detail.detail || "Approve failed.";
      }
    }
  });
  updateApprove(form);
});
