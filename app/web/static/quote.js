/* Quote/bill qty steppers, decimal-aware (0.5 kg + 1 = 1.5 kg).

Task 32: qty changes also refresh the line amount and the page total
immediately from the published rate. Display only: the server recomputes
every total on post, and the Update button stays the source of truth.
*/
document.addEventListener("DOMContentLoaded", () => {
  function prefixOf(sample) {
    const prefix = (sample || "").replace(/[\d.,\s-]/g, "");
    if (/[A-Za-z]$/.test(prefix)) {
      return prefix + " ";
    }
    return prefix;
  }

  function formatAmount(value, prefix) {
    const rounded = Math.round(value * 100) / 100;
    const useIndian = prefix.indexOf("₹") !== -1;
    const grouped = rounded.toLocaleString(useIndian ? "en-IN" : "en-US", {
      maximumFractionDigits: 2,
    });
    return prefix + grouped;
  }

  function lineNumbers(line) {
    const input = line.querySelector('input[type="number"]');
    const rate = parseFloat(line.getAttribute("data-rate") || "");
    const per = parseFloat(line.getAttribute("data-per") || "");
    if (!input || !(rate > 0) || !(per > 0)) {
      return null;
    }
    return { input, rate, per };
  }

  function lineAmount(line) {
    const field = line.querySelector('input[name^="amount_"]');
    if (!field) {
      return null;
    }
    const value = parseFloat(field.value || "0") || 0;
    return value > 0 ? value : null;
  }

  function refreshReceipt(scope) {
    const lines = Array.from(scope.querySelectorAll("[data-line]"));
    let total = 0;
    lines.forEach((line) => {
      const fixed = lineAmount(line);
      const amountEl = line.querySelector("[data-amount]");
      if (fixed !== null) {
        total += fixed;
        if (amountEl) {
          amountEl.textContent = formatAmount(
            fixed, prefixOf(amountEl.textContent));
        }
        return;
      }
      const parsed = lineNumbers(line);
      if (!parsed) {
        return;
      }
      const qty = Math.max(0, parseFloat(parsed.input.value || "0") || 0);
      const lineTotal = (qty / parsed.per) * parsed.rate;
      total += lineTotal;
      if (amountEl) {
        amountEl.textContent = formatAmount(
          lineTotal, prefixOf(amountEl.textContent));
      }
    });
    document.querySelectorAll("[data-total]").forEach((totalEl) => {
      totalEl.textContent = formatAmount(total, prefixOf(totalEl.textContent));
    });
  }

  function refreshTap(form) {
    const summary = form.querySelector("[data-tap-summary]");
    if (!summary) {
      return;
    }
    const zero = form.getAttribute("data-zero") || "";
    const prefix = prefixOf(zero) || prefixOf("₹0");
    let count = 0;
    let total = 0;
    form.querySelectorAll("[data-line]").forEach((line) => {
      const fixed = lineAmount(line);
      if (fixed !== null) {
        count += 1;
        total += fixed;
        return;
      }
      const parsed = lineNumbers(line);
      if (!parsed) {
        return;
      }
      const qty = Math.max(0, parseFloat(parsed.input.value || "0") || 0);
      if (qty > 0) {
        count += 1;
        total += (qty / parsed.per) * parsed.rate;
      }
    });
    if (!count) {
      summary.textContent = "Pick items with +";
      return;
    }
    const noun = count === 1 ? "item" : "items";
    summary.textContent = `${count} ${noun} · ${formatAmount(total, prefix)}`;
  }

  document.querySelectorAll("[data-stepper]").forEach((stepper) => {
    const input = stepper.querySelector('input[type="number"]');
    if (!input) {
      return;
    }
    function changed() {
      const receipt = stepper.closest("[data-receipt]");
      if (receipt) {
        refreshReceipt(receipt);
      }
      const tapForm = stepper.closest("[data-tap-form]");
      if (tapForm) {
        refreshTap(tapForm);
      }
    }
    stepper.querySelectorAll("[data-step]").forEach((button) => {
      button.addEventListener("click", () => {
        const current = parseFloat(input.value || "0") || 0;
        const delta = parseFloat(button.getAttribute("data-step")) || 0;
        const next = Math.max(0, Math.round((current + delta) * 100) / 100);
        input.value = String(next);
        changed();
      });
    });
    input.addEventListener("change", changed);
    input.addEventListener("input", changed);
  });
});
