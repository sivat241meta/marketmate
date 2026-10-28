/* Quick tap-billing (Task 36): weight/piece chips plus a shared keypad
   sheet for rupee amounts ("Rs 20 worth") and exact weights in g or kg.
   Chips only set the existing qty/unit/amount inputs; the server recomputes
   every total on post. */

document.addEventListener("DOMContentLoaded", () => {
  const keypad = document.querySelector("[data-keypad]");
  const display = keypad ? keypad.querySelector("[data-keypad-display]") : null;
  const unitBtn = keypad ? keypad.querySelector("[data-keypad-unit]") : null;
  const okBtn = keypad ? keypad.querySelector("[data-keypad-ok]") : null;
  const cancelBtn = keypad ? keypad.querySelector("[data-keypad-cancel]") : null;

  let mode = null;
  let activeLine = null;
  let buffer = "";
  let weightUnit = "g";

  function lineInputs(line) {
    return {
      qty: line.querySelector('input[name^="qty_"]'),
      unit: line.querySelector('input[name^="unit_"]'),
      amount: line.querySelector('input[name^="amount_"]'),
      label: line.querySelector("[data-amount-label]"),
    };
  }

  function fireChanged(input) {
    if (!input) {
      return;
    }
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function clearAmount(line) {
    const parts = lineInputs(line);
    if (parts.amount) {
      parts.amount.value = "";
    }
    if (parts.label) {
      parts.label.textContent = "";
      parts.label.hidden = true;
    }
  }

  function revealStepper(line) {
    const add = line.querySelector("[data-add]");
    const stepper = line.querySelector("[data-stepper]");
    if (add) {
      add.hidden = true;
    }
    if (stepper) {
      stepper.hidden = false;
    }
  }

  function setQty(line, qty, unit) {
    const parts = lineInputs(line);
    if (!parts.qty) {
      return;
    }
    parts.qty.value = String(qty);
    if (unit && parts.unit) {
      parts.unit.value = unit;
    }
    clearAmount(line);
    revealStepper(line);
    fireChanged(parts.qty);
  }

  function setAmount(line, amount) {
    const parts = lineInputs(line);
    if (!parts.amount) {
      return;
    }
    parts.amount.value = String(amount);
    if (parts.qty) {
      parts.qty.value = "0";
      fireChanged(parts.qty);
    }
    if (parts.label) {
      parts.label.textContent = "₹" + amount + " worth";
      parts.label.hidden = false;
    }
    revealStepper(line);
  }

  function refreshDisplay() {
    if (!display) {
      return;
    }
    const shown = buffer === "" ? "0" : buffer;
    if (mode === "amount") {
      display.textContent = "₹" + shown + " worth";
    } else if (mode === "weight") {
      display.textContent = shown + " " + weightUnit;
    } else {
      display.textContent = shown;
    }
    if (unitBtn) {
      unitBtn.hidden = mode !== "weight";
      unitBtn.textContent = weightUnit;
    }
  }

  function openKeypad(nextMode, line, startUnit) {
    if (!keypad) {
      return;
    }
    mode = nextMode;
    activeLine = line;
    buffer = "";
    weightUnit = startUnit === "kg" ? "kg" : "g";
    keypad.hidden = false;
    refreshDisplay();
  }

  function closeKeypad() {
    if (!keypad) {
      return;
    }
    keypad.hidden = true;
    mode = null;
    activeLine = null;
    buffer = "";
  }

  document.querySelectorAll("[data-tap-form] [data-line]").forEach((line) => {
    const add = line.querySelector("[data-add]");
    const stepper = line.querySelector("[data-stepper]");
    const qty = line.querySelector('input[name^="qty_"]');
    if (!add || !stepper || !qty) {
      return;
    }
    if ((parseFloat(qty.value || "0") || 0) > 0) {
      add.hidden = true;
      return;
    }
    stepper.hidden = true;
    add.hidden = false;
    add.addEventListener("click", () => {
      revealStepper(line);
    });
  });

  document.querySelectorAll("[data-chips]").forEach((box) => {
    const line = box.closest("[data-line]");
    if (!line) {
      return;
    }
    box.querySelectorAll("[data-chip]").forEach((button) => {
      button.addEventListener("click", () => {
        const chip = button.getAttribute("data-chip") || "";
        const parts = lineInputs(line);
        const unit = (parts.unit && parts.unit.value) || box.getAttribute("data-unit") || "";
        if (chip.endsWith("g") && chip !== "+6" && chip !== "+12") {
          const grams = parseFloat(chip.slice(0, -1));
          if (!(grams > 0)) {
            return;
          }
          if (unit === "g") {
            setQty(line, grams, "g");
          } else {
            setQty(line, Math.round((grams / 1000) * 1000) / 1000, "kg");
          }
        } else if (chip === "+1" || chip === "+6" || chip === "+12") {
          const add = parseInt(chip.slice(1), 10);
          const current = parts.qty ? parseFloat(parts.qty.value || "0") || 0 : 0;
          if (unit === "dozen") {
            const next = Math.round((current + add / 12) * 10000) / 10000;
            setQty(line, next, "dozen");
          } else {
            setQty(line, current + add, parts.unit ? parts.unit.value : unit);
          }
        } else if (chip === "amount") {
          openKeypad("amount", line, unit);
        } else if (chip === "keypad") {
          openKeypad("weight", line, unit);
        }
      });
    });
    const qtyInput = line.querySelector('input[name^="qty_"]');
    if (qtyInput) {
      qtyInput.addEventListener("input", () => {
        const parts = lineInputs(line);
        if (parts.amount && parts.amount.value) {
          clearAmount(line);
        }
      });
    }
  });

  if (keypad) {
    keypad.querySelectorAll("[data-key]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.getAttribute("data-key") || "";
        if (key === "clear") {
          buffer = "";
        } else if (key === "back") {
          buffer = buffer.slice(0, -1);
        } else if (key === "dot") {
          if (!buffer.includes(".") && buffer.length < 7) {
            buffer = buffer === "" ? "0." : buffer + ".";
          }
        } else if (/^[0-9]$/.test(key) && buffer.length < 7) {
          buffer += key;
        }
        refreshDisplay();
      });
    });
    if (unitBtn) {
      unitBtn.addEventListener("click", () => {
        weightUnit = weightUnit === "g" ? "kg" : "g";
        refreshDisplay();
      });
    }
    if (cancelBtn) {
      cancelBtn.addEventListener("click", closeKeypad);
    }
    if (okBtn) {
      okBtn.addEventListener("click", () => {
        if (!activeLine) {
          closeKeypad();
          return;
        }
        const value = parseFloat(buffer || "0") || 0;
        if (!(value > 0)) {
          closeKeypad();
          return;
        }
        if (mode === "amount") {
          setAmount(activeLine, Math.round(value * 100) / 100);
        } else if (mode === "weight") {
          setQty(activeLine, value, weightUnit);
        }
        closeKeypad();
      });
    }
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !keypad.hidden) {
        closeKeypad();
      }
    });
  }
});
