/* Task 27: quote qty steppers, decimal-aware (0.5 kg + 1 = 1.5 kg). */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-stepper]").forEach((stepper) => {
    const input = stepper.querySelector('input[type="number"]');
    if (!input) {
      return;
    }
    stepper.querySelectorAll("[data-step]").forEach((button) => {
      button.addEventListener("click", () => {
        const current = parseFloat(input.value || "0") || 0;
        const delta = parseFloat(button.getAttribute("data-step")) || 0;
        const next = Math.max(0, Math.round((current + delta) * 100) / 100);
        input.value = String(next);
      });
    });
  });
});
