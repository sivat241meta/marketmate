"use strict";
/* Review cards: tapping an option fills the first price input and marks the
   flag resolved (chosen button gets a check). On TWO_PRICES the other
   duplicate lines are removed from the card, so approval keeps one line.
   Approve posts the edited cards as JSON.
   Option buttons carry data-target-field (never data-field) so input queries
   below only ever match real inputs and selects. */

let approveAttempted = false;

function cardInputs(form, index) {
  return Array.from(form.querySelectorAll(
    `input[data-item="${index}"][data-field],` +
    ` select[data-item="${index}"][data-field]`));
}

function collectCards(form) {
  const proofs = {};
  form.querySelectorAll(".proof-data").forEach((node) => {
    proofs[node.dataset.item] = JSON.parse(node.textContent);
  });
  const names = {};
  form.querySelectorAll(".card[data-card]").forEach((card) => {
    const head = card.querySelector("h2");
    if (!head) {
      return;
    }
    const local = head.querySelector(".name-local");
    const en = head.querySelector(".name-en");
    if (!local || !en) {
      return;
    }
    names[card.dataset.card] = {
      local: local.textContent.trim(),
      en: en.textContent.trim(),
    };
  });
  const byItem = {};
  form.querySelectorAll("input[data-item][data-field], select[data-item][data-field]").forEach((input) => {
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
  const order = (a, b) => Number(a) - Number(b);
  const items = Object.keys(byItem).sort(order).map((key, position) => {
    const entry = byItem[key];
    const lines = Object.keys(entry.lines).sort(order).map((line) => entry.lines[line]);
    const box = form.querySelector(`input[data-card-confirm][data-item="${key}"]`);
    if (box && box.checked) {
      confirmed.push(position);
    }
    const proof = proofs[key] || {};
    return {
      name_spoken: names[key] ? names[key].en : "",
      name_local: names[key] ? names[key].local : "",
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
        source: proof.source || null,
      },
      flags: [], photo: null, condition_hint: null, confirmed: false,
    };
  });
  const carried = [];
  form.querySelectorAll("input[data-carried]").forEach((box) => {
    if (box.checked) {
      const raw = box.dataset.id || box.value;
      const num = Number(raw);
      carried.push(Number.isNaN(num) ? raw : num);
    }
  });
  return { items, confirmed, carried };
}

function lineKey(wrap) {
  const amount = wrap.querySelector('input[data-field="per_amount"]');
  const unit = wrap.querySelector(
    'select[data-field="unit"], input[data-field="unit"]');
  return `${amount ? amount.value : ""}||${unit ? unit.value : ""}`;
}

function keepChosenLine(card) {
  if (!card) {
    return;
  }
  const wraps = Array.from(card.querySelectorAll(".line"));
  if (wraps.length < 2) {
    return;
  }
  const keep = lineKey(wraps[0]);
  wraps.slice(1).forEach((wrap) => {
    if (lineKey(wrap) === keep) {
      wrap.remove();
    }
  });
}

function isHiddenBox(box) {
  return box.closest("[hidden]") !== null;
}

function cardEdited(card) {
  const initial = Number(card.dataset.initialLines || 0);
  const current = card.querySelectorAll(".line").length;
  if (initial && current < initial) {
    return true;
  }
  const fields = card.querySelectorAll(
    'input[data-field="price"], select[data-field="price"],' +
    ' input[data-field="per_amount"], select[data-field="per_amount"],' +
    ' input[data-field="unit"], select[data-field="unit"]');
  for (const input of fields) {
    const original = input.dataset.original ?? "";
    if ((input.value ?? "") !== original) {
      return true;
    }
  }
  return false;
}

function expandCard(card) {
  if (!card || !card.classList.contains("is-collapsed")) {
    return;
  }
  card.classList.remove("is-collapsed");
  const toggle = card.querySelector("[data-card-toggle]");
  if (toggle) {
    toggle.setAttribute("aria-expanded", "true");
  }
}

function showConfirm(card) {
  expandCard(card);
  const wrap = card.querySelector("[data-confirm-wrap]");
  const note = card.querySelector("[data-edit-note]");
  const box = card.querySelector("[data-card-confirm]");
  if (wrap) {
    wrap.hidden = false;
  }
  if (note) {
    note.hidden = false;
  }
  if (box) {
    box.checked = false;
  }
}

function hideConfirmIfClean(card) {
  const wrap = card.querySelector("[data-confirm-wrap]");
  const note = card.querySelector("[data-edit-note]");
  if (cardEdited(card)) {
    return;
  }
  if (wrap) {
    if (note) {
      note.hidden = true;
    }
    wrap.hidden = true;
  } else if (note) {
    note.hidden = true;
  }
}

function syncCardConfirm(card) {
  if (cardEdited(card)) {
    showConfirm(card);
  } else {
    hideConfirmIfClean(card);
  }
}

function cardNeeds(card) {
  let needs = false;
  card.querySelectorAll(".flag-options").forEach((group) => {
    if (!group.querySelector(".opt-btn.chosen")) {
      needs = true;
    }
  });
  card.querySelectorAll("[data-card-confirm]").forEach((box) => {
    if (!box.checked && !isHiddenBox(box)) {
      needs = true;
    }
  });
  return needs;
}

function needText(form, need) {
  if (need === 1) {
    return form.dataset.msgNeedOne;
  }
  return (form.dataset.msgNeedMany || "").replace("{n}", String(need));
}

function fillCounts(template, ok, total, need) {
  return (template || "")
    .replace("{ok}", String(ok))
    .replace("{total}", String(total))
    .replace("{need}", String(need));
}

function updateCounts(form, need) {
  const cards = form.querySelectorAll(".card[data-card]");
  const total = cards.length;
  const ok = total - need;
  const counts = document.querySelector("[data-review-counts]");
  if (counts) {
    counts.textContent = fillCounts(form.dataset.msgCounts, ok, total, need);
  }
  const bar = document.querySelector("[data-review-bar]");
  if (bar) {
    bar.value = ok;
    bar.max = total;
    bar.setAttribute(
      "aria-label", fillCounts(form.dataset.msgCountsAria, ok, total, need));
  }
  const sticky = form.querySelector("[data-approve-count]");
  if (sticky) {
    sticky.textContent =
      need === 0
        ? form.dataset.msgReady
        : `${needText(form, need)}.`;
  }
}

function updateApprove(form) {
  const button = form.querySelector("#approve-btn");
  const error = form.querySelector("#approve-error");
  let need = 0;
  form.querySelectorAll(".card[data-card]").forEach((card) => {
    if (cardNeeds(card)) {
      need += 1;
    }
  });
  button.disabled = need > 0;
  updateCounts(form, need);
  if (error) {
    if (error.dataset.serverMessage === "true") {
      return;
    }
    error.hidden = !approveAttempted || need === 0;
    if (!error.hidden) {
      error.textContent = `${needText(form, need)}.`;
    }
  }
}

function revealNeedsConfirm(form, needs) {
  let firstCard = null;
  for (const need of needs || []) {
    const card = form.querySelector(`.card[data-card="${need.index}"]`);
    if (!card) {
      continue;
    }
    const wrap = card.querySelector("[data-confirm-wrap]");
    const note = card.querySelector("[data-edit-note]");
    const box = card.querySelector("[data-card-confirm]");
    if (wrap) {
      wrap.hidden = false;
    }
    if (note) {
      note.hidden = false;
      if (need.messages && need.messages.length) {
        note.textContent =
          `${need.messages.join(" ")} ${form.dataset.msgPlayConfirm}`;
      }
    }
    if (box) {
      box.checked = false;
    }
    expandCard(card);
    if (!firstCard) {
      firstCard = card;
    }
  }
  if (firstCard && firstCard.scrollIntoView) {
    firstCard.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("review-form");
  if (!form) {
    return;
  }
  form.querySelectorAll("[data-carried-clear]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      form.querySelectorAll("input[data-carried]").forEach((box) => {
        box.checked = false;
      });
    });
  });
  form.querySelectorAll(".card[data-card]").forEach((card) => {
    card.dataset.initialLines = String(card.querySelectorAll(".line").length);
  });
  form.querySelectorAll("[data-card-toggle]").forEach((toggle) => {
    toggle.addEventListener("click", () => {
      const card = toggle.closest(".card");
      if (!card) {
        return;
      }
      card.classList.toggle("is-collapsed");
      toggle.setAttribute(
        "aria-expanded",
        card.classList.contains("is-collapsed") ? "false" : "true",
      );
    });
  });
  form.querySelectorAll(".opt-btn").forEach((button) => {
    button.addEventListener("click", () => {
      const group = button.closest(".flag-options");
      group.querySelectorAll(".opt-btn").forEach((other) => {
        other.classList.remove("chosen");
      });
      button.classList.add("chosen");
      const field = button.dataset.targetField || "price";
      const input = form.querySelector(
        `input[data-item="${button.dataset.item}"][data-field="${field}"],` +
        ` select[data-item="${button.dataset.item}"][data-field="${field}"]`);
      if (input) {
        input.value = button.dataset.value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (group.dataset.flag === "TWO_PRICES") {
        keepChosenLine(button.closest(".card"));
      }
      const card = button.closest(".card");
      if (card) {
        const box = card.querySelector("[data-card-confirm]");
        if (box && isHiddenBox(box)) {
          // Board-price tap doubles as the tick; the box stays hidden.
          box.checked = true;
        }
        syncCardConfirm(card);
      }
      updateApprove(form);
    });
  });
  form.querySelectorAll(".line-remove").forEach((button) => {
    button.addEventListener("click", () => {
      const card = button.closest(".card");
      const wrap = button.closest(".line");
      if (wrap) {
        wrap.remove();
      }
      if (card) {
        showConfirm(card);
      }
      updateApprove(form);
    });
  });
  form.addEventListener("input", (event) => {
    const card = event.target ? event.target.closest(".card") : null;
    if (card) {
      syncCardConfirm(card);
    }
    updateApprove(form);
  });
  form.addEventListener("change", (event) => {
    const card = event.target ? event.target.closest(".card") : null;
    if (card) {
      syncCardConfirm(card);
    }
    updateApprove(form);
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    approveAttempted = true;
    updateApprove(form);
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
      if (detail && detail.needs_confirm) {
        revealNeedsConfirm(form, detail.needs_confirm);
      }
      if (error) {
        error.hidden = false;
        error.dataset.serverMessage = "true";
        error.textContent = detail.detail || form.dataset.msgApproveFailed;
      }
      updateApprove(form);
      if (error) {
        error.hidden = false;
        delete error.dataset.serverMessage;
        if (detail.detail) {
          error.textContent = detail.detail;
        }
      }
    }
  });
  updateApprove(form);
});
