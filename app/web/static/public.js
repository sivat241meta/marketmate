/* Shared public pages (Task 90): phone menu sheet + search-card tabs.
   Mirrors the homepage behavior from home.js for every non-homepage
   public page (the homepage loads home.js instead, so this never
   double-binds there). Makes no network calls. */
(function () {
  "use strict";

  function initMenu() {
    var btn = document.querySelector("[data-menu-open]");
    var sheet = document.getElementById("mobile-nav");
    if (!btn || !sheet || btn.dataset.mmBound) {
      return;
    }
    btn.dataset.mmBound = "1";
    btn.addEventListener("click", function () {
      var open = sheet.hidden;
      sheet.hidden = !open;
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    sheet.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        sheet.hidden = true;
        btn.setAttribute("aria-expanded", "false");
      });
    });
  }

  function initTabs() {
    document.querySelectorAll("form.hp-search").forEach(function (form) {
      if (form.dataset.mmBound) {
        return;
      }
      form.dataset.mmBound = "1";
      var input = form.querySelector("input[type=\"search\"]");
      var tabs = form.querySelectorAll(".hp-tab[data-ph]");
      tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
          tabs.forEach(function (other) {
            var on = other === tab;
            other.classList.toggle("on", on);
            other.setAttribute("aria-selected", on ? "true" : "false");
          });
          if (input) {
            input.placeholder = tab.getAttribute("data-ph") || "";
            input.focus();
          }
        });
      });
    });
  }

  function init() {
    initMenu();
    initTabs();
  }

  if (typeof document !== "undefined" && document) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }
})();
