/* Task 78: live mode for the Meta AI calls page. Polls the JSON endpoint
   every 2 s while a price session is processing and prepends new rows.
   No external libraries. */
(function () {
  "use strict";

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) {
      node.className = cls;
    }
    if (text !== undefined && text !== null) {
      node.textContent = text;
    }
    return node;
  }

  function buildRow(row, labels) {
    const wrap = el("div", "list-row ai-row is-new");
    wrap.setAttribute("data-ai-row", "");
    wrap.setAttribute("data-id", String(row.id));
    wrap.setAttribute("data-kind", row.kind || "other");
    const main = el("div", "list-main");
    const name = el("span", "list-name");
    name.appendChild(el("code", "ai-model", row.model));
    if (row.spark_kind) {
      name.appendChild(document.createTextNode(" "));
      name.appendChild(el("span", "muted", row.spark_kind));
    }
    main.appendChild(name);
    const sub = [];
    if (row.step_label) {
      sub.push(row.step_label);
    }
    if (row.summary) {
      sub.push(row.summary);
    }
    main.appendChild(el("span", "list-sub", sub.join(" · ")));
    wrap.appendChild(main);
    const price = el("div", "list-price");
    price.appendChild(el("span", null, row.cost));
    const small = [row.time];
    if (row.latency) {
      small.push(row.latency);
    }
    price.appendChild(el("small", null, small.join(" · ")));
    wrap.appendChild(price);
    const failed = row.ok === false;
    wrap.appendChild(el("span", "pill " + (failed ? "pill-danger" : "pill-live"),
      failed ? labels.failed : labels.ok));
    window.setTimeout(() => wrap.classList.remove("is-new"), 2500);
    return wrap;
  }

  function buildGroup(row, sessionBase) {
    const group = el("section", "list-card");
    group.setAttribute(
      "data-ai-group",
      row.session_id === null || row.session_id === undefined
        ? "none" : String(row.session_id));
    const head = el("h2", "section-head ai-group-head");
    head.appendChild(el("span", null, row.session_title));
    if (row.session_id !== null && row.session_id !== undefined) {
      head.appendChild(document.createTextNode(" "));
      const link = el("a", null, "#" + row.session_id);
      link.setAttribute("href", sessionBase + row.session_id);
      head.appendChild(link);
    }
    group.appendChild(head);
    return group;
  }

  function init() {
    const list = document.querySelector("[data-ai-list]");
    if (!list || list.getAttribute("data-ai-live") !== "1") {
      return;
    }
    const labels = {
      ok: list.getAttribute("data-ai-ok") || "ok",
      failed: list.getAttribute("data-ai-failed") || "failed",
    };
    const sessionBase = list.getAttribute("data-ai-session-base") || "";
    let since = list.getAttribute("data-ai-since") || "0";
    let failures = 0;

    async function poll() {
      const sep = list.getAttribute("data-ai-poll").includes("?") ? "&" : "?";
      const url = list.getAttribute("data-ai-poll") + sep + "since_id=" + since;
      let data;
      try {
        const response = await fetch(url, { headers: { Accept: "application/json" } });
        if (!response.ok) {
          throw new Error("poll failed");
        }
        data = await response.json();
      } catch (err) {
        failures += 1;
        if (failures >= 5) {
          window.clearInterval(timer);
        }
        return;
      }
      failures = 0;
      since = String(data.max_id || since);
      const rows = Array.isArray(data.rows) ? data.rows : [];
      if (rows.length) {
        const empty = list.querySelector(".empty-state");
        if (empty) {
          empty.remove();
        }
        /* Server sends newest first; insert oldest first so the
           newest row ends up on top. */
        for (const row of [...rows].reverse()) {
          const key = row.session_id === null || row.session_id === undefined
            ? "none" : String(row.session_id);
          let group = list.querySelector('[data-ai-group="' + key + '"]');
          if (!group) {
            group = buildGroup(row, sessionBase);
            list.prepend(group);
          }
          const head = group.querySelector(".ai-group-head");
          const node = buildRow(row, labels);
          if (head && head.nextSibling) {
            head.after(node);
          } else {
            group.appendChild(node);
          }
        }
        const calls = document.querySelector("[data-ai-calls]");
        if (calls && data.stats && typeof data.stats.calls === "number") {
          calls.textContent = String(data.stats.calls);
        }
        const cost = document.querySelector("[data-ai-cost]");
        if (cost && data.cost_text) {
          cost.textContent = data.cost_text;
        }
        const avg = document.querySelector("[data-ai-avg]");
        if (avg && data.avg_text) {
          avg.textContent = data.avg_text;
        }
        const wall = document.querySelector("[data-ai-wall]");
        if (wall && data.wall_text) {
          wall.textContent = data.wall_text;
        }
      }
      if (!data.processing) {
        window.clearInterval(timer);
        const note = document.querySelector("[data-ai-live]");
        if (note) {
          note.remove();
        }
      }
    }

    const timer = window.setInterval(poll, 2000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
