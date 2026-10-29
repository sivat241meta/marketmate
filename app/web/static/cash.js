/* Cash helper (Task 50, Task 101): "Customer gave" change math.

   The field ships pre-filled with the bill total. Focusing it selects
   the whole value so typing replaces it (no "140200"), and the first
   on-screen keypad press replaces the untouched prefill the same way.
   Chips (50/100/200/500/exact) set the value outright as before.
*/
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-cash]").forEach((box) => {
    const total = parseFloat(box.getAttribute("data-total") || "0") || 0;
    const input = box.querySelector("[data-cash-gave]");
    const back = box.querySelector("[data-cash-back]");
    if (!input || !back) { return; }
    let touched = false;
    function fmt(value) {
      const rounded = Math.round(value * 100) / 100;
      return "₹" + rounded.toLocaleString("en-IN", { maximumFractionDigits: 2 });
    }
    function refresh() {
      const gave = parseFloat(input.value || "0") || 0;
      const due = Math.max(0, gave - total);
      back.textContent = fmt(due);
    }
    input.addEventListener("focus", () => {
      if (input.select) {
        input.select();
      }
    });
    input.addEventListener("input", () => {
      touched = true;
      refresh();
    });
    box.querySelectorAll("[data-cash-chip]").forEach((chip) => {
      chip.addEventListener("click", () => {
        const kind = chip.getAttribute("data-cash-chip");
        if (kind === "exact") {
          input.value = String(Math.round(total * 100) / 100);
        } else {
          input.value = kind;
        }
        touched = true;
        refresh();
      });
    });
    const keys = box.querySelector("[data-cash-keys]");
    if (keys) {
      keys.querySelectorAll("[data-key]").forEach((key) => {
        key.addEventListener("click", () => {
          const k = key.getAttribute("data-key");
          if (!touched) {
            input.value = "";
            touched = true;
          }
          const current = input.value || "";
          if (k === "clear") { input.value = ""; }
          else if (k === "back") { input.value = current.slice(0, -1); }
          else { input.value = (current === "0" ? "" : current) + k; }
          refresh();
        });
      });
    }
    refresh();
  });
});
