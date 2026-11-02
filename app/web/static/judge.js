"use strict";
/* Task 159: judge step 2 polls the same session status JSON as the seller
   session page. Each poll refreshes the 3 Meta-model rows and the elapsed
   line; a finished/needs-action status reloads into step 3 or 4. */

document.addEventListener("DOMContentLoaded", () => {
  const block = document.querySelector("[data-judge-status]");
  if (!block) {
    return;
  }
  const url = block.dataset.statusUrl;
  const order = (block.dataset.stageOrder || "").split(",");
  const elapsedEl = document.querySelector("[data-judge-elapsed]");
  const friendlyEl = document.querySelector("[data-judge-friendly]");

  // Mirrors seller._judge_model_states: voice covers listening, spark
  // brackets SAM (items, photo verify, checks), SAM covers photos.
  function statesFor(stage) {
    let pos = order.indexOf(stage || "uploaded");
    if (pos < 0) {
      pos = 0;
    }
    const voice = pos > 2 ? "done" : pos === 2 ? "active" : "todo";
    const spark = pos > 6 ? "done" : pos >= 4 ? "active" : "todo";
    const sam = pos > 5 ? "done" : pos === 5 ? "active" : "todo";
    return { voice, spark, sam };
  }

  function fmtElapsed(seconds) {
    const total = Math.max(0, Math.round(seconds || 0));
    const sTmpl = block.dataset.elapsedS;
    const mTmpl = block.dataset.elapsedM;
    if (total < 60) {
      return sTmpl
        ? sTmpl.replace("__S__", String(total))
        : "Elapsed: " + total + " s";
    }
    const m = Math.floor(total / 60);
    const s = total % 60;
    return mTmpl
      ? mTmpl.replace("__M__", String(m)).replace("__S__", String(s))
      : "Elapsed: " + m + " min " + s + " s";
  }

  function paint(states) {
    block.querySelectorAll("[data-model]").forEach((row) => {
      const state = states[row.dataset.model];
      if (!state) {
        return;
      }
      row.classList.remove("is-done", "is-active", "is-todo");
      row.classList.add("is-" + state);
      const dot = row.querySelector(".jdot");
      if (dot) {
        dot.textContent = state === "done" ? "\u2713" : "";
      }
    });
  }

  async function poll() {
    let data;
    try {
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        return;
      }
      data = await response.json();
    } catch (err) {
      return;
    }
    if (
      data.status === "review" ||
      data.status === "approved" ||
      data.status === "failed" ||
      data.stage === "language_check" ||
      data.needs_action
    ) {
      window.location.reload();
      return;
    }
    paint(statesFor(data.stage));
    if (elapsedEl) {
      elapsedEl.textContent = fmtElapsed(data.elapsed_s);
    }
    if (friendlyEl && data.friendly) {
      friendlyEl.textContent = data.friendly;
    }
  }

  window.setInterval(poll, 1500);
});
