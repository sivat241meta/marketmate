/* Task 26: photo result page - boxes toggle, count steppers, suggestion sync. */
document.addEventListener("DOMContentLoaded", () => {
  const frame = document.querySelector("[data-photo-frame]");
  const toggle = document.getElementById("show-boxes");
  if (frame && toggle) {
    toggle.addEventListener("change", () => {
      frame.classList.toggle("is-hiding-boxes", !toggle.checked);
    });
  }

  function syncSuggestion(name, value) {
    document.querySelectorAll("[data-qty-for]").forEach((hidden) => {
      if (hidden.getAttribute("data-qty-for") === name) {
        hidden.value = value;
      }
    });
  }

  document.querySelectorAll("[data-stepper]").forEach((stepper) => {
    const input = stepper.querySelector("[data-count-for]");
    if (!input) {
      return;
    }
    const name = input.getAttribute("data-count-for");
    syncSuggestion(name, input.value);
    stepper.querySelectorAll("[data-step]").forEach((button) => {
      button.addEventListener("click", () => {
        const current = parseInt(input.value || "0", 10) || 0;
        const next = Math.max(
          0, current + parseInt(button.getAttribute("data-step"), 10));
        input.value = String(next);
        syncSuggestion(name, input.value);
      });
    });
    input.addEventListener("change", () => {
      const clean = Math.max(0, parseInt(input.value || "0", 10) || 0);
      input.value = String(clean);
      syncSuggestion(name, input.value);
    });
  });
});
