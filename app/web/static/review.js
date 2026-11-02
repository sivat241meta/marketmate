"use strict";
/* Review cards: tapping an option fills the first price input and marks the
   flag resolved (chosen button gets a check). On TWO_PRICES the other
   duplicate lines are removed from the card, so approval keeps one line.
   On QTY_AS_PRICE / MULTI_PRICE_UNCLEAR the tapped option ("Rs.20 for
   5 pieces") keeps its line and drops the other lines the same way.
   On MISSED_PRICE the "Remove" tap drops the whole card and its index
   rides along as `removed`, so the server drops the same stored draft.
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
      variety: card.dataset.renamed ? (card.dataset.variety || null) : null,
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
      variety: names[key] ? (names[key].variety || null) : null,
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
  return { items, confirmed, carried, removed: removedIndexes(form) };
}

function removedIndexes(form) {
  try {
    const raw = JSON.parse((form.dataset && form.dataset.removed) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch (e) {
    return [];
  }
}

function removeMissedCard(form, card) {
  // A MISSED_PRICE "Remove" tap drops the whole card: the seller says
  // the heard price was not real. The removed index rides along so the
  // server drops the same stored draft.
  if (card && card.dataset && card.dataset.card !== undefined) {
    const key = Number(card.dataset.card);
    const removed = removedIndexes(form);
    if (!removed.includes(key)) {
      removed.push(key);
      form.dataset.removed = JSON.stringify(removed);
    }
    card.remove();
  }
  updateApprove(form);
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

function isConfirmBox(target) {
  if (!target) {
    return false;
  }
  if (typeof target.matches === "function") {
    try {
      if (target.matches("[data-card-confirm]")) {
        return true;
      }
    } catch (e) {
      // fall through to dataset check
    }
  }
  return !!(target.dataset && ("cardConfirm" in target.dataset));
}

function isLineChoiceFlag(code) {
  return code === "TWO_PRICES" || code === "QTY_AS_PRICE" ||
    code === "MULTI_PRICE_UNCLEAR";
}

function isSelfConfirmFlag(code) {
  return code === "SOUND_ALIKE" || isLineChoiceFlag(code);
}

function singularUnit(word) {
  const map = {
    pieces: "piece", dozens: "dozen", bunches: "bunch",
    packets: "packet",
  };
  const lower = String(word || "").toLowerCase();
  return map[lower] || lower;
}

function parseLineOption(text) {
  // "Rs.20 for 5 pieces" or "Rs.5 per kg" (see checks._describe_line).
  // "per <unit>" implies a per-amount of 1 but also matches a blank one.
  const m = String(text || "").match(
    /^₹\s*([\d.]+)\s+(?:for\s+([\d.]+)\s+([A-Za-z]+)|per\s+([A-Za-z]+))$/);
  if (!m) {
    return null;
  }
  if (m[4]) {
    return { price: m[1], per: "1", unit: singularUnit(m[4]), perImplied: true };
  }
  return {
    price: m[1], per: m[2], unit: singularUnit(m[3]), perImplied: false,
  };
}

function keepOptionLine(card, value) {
  if (!card) {
    return;
  }
  const want = parseLineOption(value);
  if (!want) {
    return;
  }
  const wraps = Array.from(card.querySelectorAll(".line"));
  if (wraps.length < 2) {
    return;
  }
  const read = (wrap, field) => {
    const el = wrap.querySelector(
      `input[data-field="${field}"], select[data-field="${field}"]`);
    return el ? el.value : "";
  };
  let keep = null;
  for (const wrap of wraps) {
    const priceOk = read(wrap, "price") !== "" &&
      Number(read(wrap, "price")) === Number(want.price);
    const unit = String(read(wrap, "unit") || "").toLowerCase();
    const per = read(wrap, "per_amount");
    const perOk = want.perImplied
      ? (per === "" || Number(per) === Number(want.per))
      : (per !== "" && Number(per) === Number(want.per));
    if (priceOk && unit === want.unit && perOk) {
      keep = wrap;
      break;
    }
  }
  if (!keep) {
    return;
  }
  wraps.forEach((wrap) => {
    if (wrap !== keep) {
      wrap.remove();
    }
  });
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
    ' input[data-field="unit"], select[data-field="unit"],' +
    ' input[data-field="qty"], select[data-field="qty"]');
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

function headlineNames(card) {
  const head = card ? card.querySelector("h2") : null;
  const local = head ? head.querySelector(".name-local") : null;
  const en = head ? head.querySelector(".name-en") : null;
  const line = card ? card.querySelector("[data-variety-line]") : null;
  return {
    local: local ? local.textContent.trim() : "",
    en: en ? en.textContent.trim() : "",
    variety: line ? line.textContent.trim() : (card.dataset.variety || ""),
  };
}

function renameCardFor(sheet) {
  const direct = sheet.closest ? sheet.closest(".card") : null;
  if (direct) {
    return direct;
  }
  // While the rename dialog is open the sheet sits in a box under
  // document.body, so DOM ancestry cannot find the card. The sheet and
  // its card share the item index instead (data-item / data-card).
  const item = sheet.dataset ? sheet.dataset.item : null;
  if (item === null || item === undefined || item === "") {
    return null;
  }
  const form = typeof document !== "undefined"
    ? document.getElementById("review-form") : null;
  const scope = form
    || (typeof document !== "undefined" ? document : null);
  return scope ? scope.querySelector(`.card[data-card="${item}"]`) : null;
}

function saveRename(sheet) {
  const dialog = typeof window !== "undefined"
    ? window.MMRenameDialog : null;
  const card = renameCardFor(sheet);
  if (!card) {
    if (dialog && dialog.isOpen()) {
      // Restores the sheet to its home in the card.
      dialog.close();
      return;
    }
    sheet.hidden = true;
    return;
  }
  const current = headlineNames(card);
  const pick = (name, fallback) => {
    const input = sheet.querySelector(`input[name="${name}"]`);
    const typed = input ? input.value.trim() : "";
    return typed || fallback;
  };
  const local = pick("name_local", current.local);
  const en = pick("name_en", current.en);
  const variety = pick("variety", current.variety);
  const changed = local !== current.local || en !== current.en
    || variety !== current.variety;
  card.querySelectorAll(".name-local").forEach((node) => {
    node.textContent = local;
  });
  card.querySelectorAll(".name-en").forEach((node) => {
    node.textContent = en;
  });
  let line = card.querySelector("[data-variety-line]");
  if (variety) {
    if (!line) {
      line = document.createElement("p");
      line.className = "muted";
      line.setAttribute("data-variety-line", "");
      const head = card.querySelector("h2");
      if (head && head.parentNode) {
        head.parentNode.insertBefore(line, head.nextSibling);
      } else {
        card.appendChild(line);
      }
    }
    line.textContent = variety;
  } else if (line) {
    line.remove();
  }
  card.dataset.variety = variety;
  if (changed) {
    card.dataset.renamed = "1";
    const mark = card.querySelector("[data-renamed-mark]");
    if (mark) {
      mark.hidden = false;
    }
  }
  if (dialog && dialog.isOpen()) {
    dialog.close();
    return;
  }
  sheet.hidden = true;
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
  form.querySelectorAll("[data-rename-open]").forEach((button) => {
    button.addEventListener("click", () => {
      const card = button.closest(".card");
      const sheet = card ? card.querySelector("[data-rename-form]") : null;
      if (!sheet) {
        return;
      }
      const current = headlineNames(card);
      const reset = (name, value) => {
        const input = sheet.querySelector(`input[name="${name}"]`);
        if (input) {
          input.value = value;
        }
      };
      reset("name_local", current.local);
      reset("name_en", current.en);
      reset("variety", current.variety);
      const dialog = typeof window !== "undefined"
        ? window.MMRenameDialog : null;
      if (dialog) {
        dialog.open(sheet, button);
        return;
      }
      sheet.hidden = false;
      const first = sheet.querySelector('input[name="name_local"]');
      if (first && first.focus) {
        first.focus();
      }
    });
  });
  form.querySelectorAll("[data-rename-form]").forEach((sheet) => {
    const save = sheet.querySelector("[data-rename-save]");
    if (save) {
      save.addEventListener("click", () => {
        saveRename(sheet);
      });
    }
    sheet.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        saveRename(sheet);
      }
    });
    const cancel = sheet.querySelector("[data-rename-cancel]");
    if (cancel) {
      cancel.addEventListener("click", () => {
        const dialog = typeof window !== "undefined"
          ? window.MMRenameDialog : null;
        if (dialog) {
          dialog.close();
          return;
        }
        sheet.hidden = true;
      });
    }
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
      const card = button.closest(".card");
      if (group && group.dataset.flag === "MISSED_PRICE" &&
          button.dataset.value === "Remove") {
        removeMissedCard(form, card);
        return;
      }
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
        // Choosing an offered option is the confirmation, not a manual
        // edit: align the baseline so the edit note stays hidden.
        input.dataset.original = button.dataset.value;
      }
      if (group.dataset.flag === "TWO_PRICES") {
        keepChosenLine(button.closest(".card"));
      } else if (group.dataset.flag === "QTY_AS_PRICE" ||
                 group.dataset.flag === "MULTI_PRICE_UNCLEAR") {
        keepOptionLine(button.closest(".card"), button.dataset.value);
      }
      if (card) {
        if (isLineChoiceFlag(group.dataset.flag)) {
          // Trimming lines is part of the choice, not an edit.
          card.dataset.initialLines = String(
            card.querySelectorAll(".line").length);
        }
        const box = card.querySelector("[data-card-confirm]");
        const code = group.dataset.flag;
        const hiddenTap = box && isHiddenBox(box);
        if (box && (isSelfConfirmFlag(code) || hiddenTap)) {
          const allResolved = Array.from(
            card.querySelectorAll(".flag-options")).every(
            (other) => other.querySelector(".opt-btn.chosen"));
          if (allResolved && !cardEdited(card)) {
            // A line-choice / SOUND_ALIKE pick (or a hidden board-price
            // tap) doubles as the tick; the box stays as-is otherwise.
            box.checked = true;
            hideConfirmIfClean(card);
            updateApprove(form);
            return;
          }
        }
        if (input) {
          input.dispatchEvent(new Event("input", { bubbles: true }));
        } else {
          syncCardConfirm(card);
          updateApprove(form);
        }
        return;
      }
      updateApprove(form);
    });
  });
  // Task 147: no photo picker any more — one square original photo
  // per card plus the retake upload below.
  form.querySelectorAll("[data-photo-retake]").forEach((input) => {
    input.addEventListener("change", async () => {
      if (!input.files || !input.files[0]) {
        return;
      }
      const body = new FormData();
      body.append("photo", input.files[0]);
      const response = await fetch(input.dataset.uploadUrl, {
        method: "POST",
        body,
      });
      if (!response.ok) {
        return;
      }
      const data = await response.json().catch(() => ({}));
      const card = input.closest(".card");
      const main = card ? card.querySelector("[data-photo-main]") : null;
      if (main && data.photo_url) {
        main.src = data.photo_url;
        // Retakes are always 4:3 crops, never cut-outs.
        main.removeAttribute("data-cutout");
      }
      input.value = "";
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
    if (isConfirmBox(event.target)) {
      updateApprove(form);
      return;
    }
    const card = event.target ? event.target.closest(".card") : null;
    if (card) {
      syncCardConfirm(card);
    }
    updateApprove(form);
  });
  form.addEventListener("change", (event) => {
    if (isConfirmBox(event.target)) {
      updateApprove(form);
      return;
    }
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
