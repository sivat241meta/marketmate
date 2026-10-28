/* Task 32: segmented method control (Speak | Type | Photo, Tap first on bills).

Without JS every panel stays visible and every plain form posts as usual.
With JS exactly one panel shows at a time.
*/
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-methods]").forEach((bar) => {
    const buttons = Array.from(bar.querySelectorAll("[data-method]"));
    const scope = bar.parentElement || document;
    const panels = Array.from(scope.querySelectorAll("[data-panel]"));
    if (!buttons.length || !panels.length) {
      return;
    }
    function show(name) {
      buttons.forEach((button) => {
        const active = button.getAttribute("data-method") === name;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
      panels.forEach((panel) => {
        panel.hidden = panel.getAttribute("data-panel") !== name;
      });
    }
    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        show(button.getAttribute("data-method"));
      });
    });
    show(buttons[0].getAttribute("data-method"));
  });
});
