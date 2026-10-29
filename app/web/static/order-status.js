/* Customer order poll (Task 60): refresh the timeline and total every
   20 s, paused while the tab is hidden. A gold "Ready for pickup!"
   banner shows when the order is ready. */
(function () {
  "use strict";

  var INTERVAL = 20000;
  var ORDER = ["new", "packing", "ready", "collected"];

  function init() {
    if (typeof document === "undefined" || !document) {
      return;
    }
    var hook = document.querySelector("[data-order-poll]");
    if (!hook) {
      return;
    }
    var url = hook.getAttribute("data-status-url") || "";
    if (!url) {
      return;
    }
    var banner = document.querySelector("[data-ready-banner]");
    var note = document.querySelector("[data-soldout-note]");
    var heading = document.querySelector("[data-status-heading]");
    var steps = Array.prototype.slice.call(
      document.querySelectorAll("[data-step-key]"));
    var checkHtml = "";
    steps.forEach(function (step) {
      var mark = step.querySelector("i");
      if (mark && mark.innerHTML && !checkHtml) {
        checkHtml = mark.innerHTML;
      }
    });
    if (!checkHtml) {
      var sent = document.querySelector("[data-timeline] i");
      if (sent && sent.innerHTML) {
        checkHtml = sent.innerHTML;
      }
    }
    var timer = null;

    function schedule() {
      if (timer) {
        clearTimeout(timer);
      }
      timer = setTimeout(poll, INTERVAL);
    }

    function apply(data) {
      if (!data) {
        return;
      }
      if (data.status === "cancelled") {
        window.location.reload();
        return;
      }
      if (data.total_fmt) {
        document.querySelectorAll("[data-total]").forEach(function (el) {
          el.textContent = data.total_fmt;
        });
      }
      var labels = {};
      (data.steps || []).forEach(function (step) {
        labels[step.key] = step.label || "";
      });
      var at = ORDER.indexOf(data.status);
      steps.forEach(function (step) {
        var key = step.getAttribute("data-step-key") || "";
        var pos = ORDER.indexOf(key);
        var isCurrent = key !== "" && key === data.status;
        var isDone = at >= 0 && pos >= 0 && pos <= at;
        step.classList.toggle("n", isCurrent);
        step.classList.toggle("d", isDone && !isCurrent);
        var now = step.querySelector("[data-now]");
        if (now) {
          now.hidden = !isCurrent;
        }
        var mark = step.querySelector("i");
        if (mark && (isDone || isCurrent) && !mark.innerHTML && checkHtml) {
          mark.innerHTML = checkHtml;
        }
      });
      if (heading && labels[data.status]) {
        heading.textContent = labels[data.status] + ".";
      }
      if (banner) {
        banner.hidden = data.status !== "ready";
      }
      if (note) {
        note.hidden = !data.sold_out;
      }
    }

    function poll() {
      if (document.hidden) {
        return;
      }
      fetch(url, { headers: { Accept: "application/json" } }).then(
        function (resp) {
          return resp.ok ? resp.json() : null;
        }).then(function (data) {
        apply(data);
        schedule();
      }).catch(function () {
        schedule();
      });
    }

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        if (timer) {
          clearTimeout(timer);
        }
      } else {
        poll();
      }
    });
    schedule();
  }

  if (typeof document !== "undefined" && document) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }
})();
