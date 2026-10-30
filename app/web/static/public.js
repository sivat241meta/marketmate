/* Shared public pages (Task 90): phone menu sheet + search-card tabs.
   Mirrors the homepage behavior from home.js for every non-homepage
   public page (the homepage loads home.js instead, so this never
   double-binds there). Makes no network calls. */
(function () {
  "use strict";

  /* Task 122: the phone menu sheet is owned by popups.js (loaded on
     every public page through the shared header). */

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

  /* Task 120: the Order-by-voice panel sits right under the search
     card and shows only when the voice tab is selected or there is
     no query (the server hides it once a typed search has results).
     Text tabs hide it again; the mic link always reveals it. */
  function initVoicePanel() {
    document.querySelectorAll("form.hp-search").forEach(function (form) {
      if (form.dataset.mmVoiceBound) {
        return;
      }
      form.dataset.mmVoiceBound = "1";
      var scope = form.parentNode || document;
      var panel = scope.querySelector
        ? scope.querySelector("[data-voice-panel]")
        : null;
      if (!panel) {
        return;
      }
      var voiceTab = form.querySelector(".hp-tab-voice");
      var micLink = form.querySelector(".hp-mic");
      var tabs = form.querySelectorAll(".hp-tab[data-ph]");
      function showPanel(show) {
        panel.hidden = !show;
        if (voiceTab) {
          voiceTab.classList.toggle("on", show);
        }
      }
      if (voiceTab) {
        voiceTab.addEventListener("click", function () {
          showPanel(panel.hidden);
        });
      }
      if (micLink) {
        micLink.addEventListener("click", function () {
          showPanel(true);
        });
      }
      tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
          showPanel(false);
        });
      });
    });
  }

  /* Task 122: market result tabs (Best basket / Shops / Items).
     Without JS every panel stays visible; with JS the first panel
     with content is shown and tabs switch between them. */
  function initMarketTabs() {
    var tabs = document.querySelectorAll("[data-mtab]");
    if (!tabs.length) {
      return;
    }
    var panels = {};
    document.querySelectorAll("[data-mtab-panel]").forEach(function (panel) {
      panels[panel.getAttribute("data-mtab-panel")] = panel;
    });
    function show(name) {
      tabs.forEach(function (tab) {
        var on = tab.getAttribute("data-mtab") === name;
        tab.classList.toggle("on", on);
        tab.setAttribute("aria-selected", on ? "true" : "false");
      });
      Object.keys(panels).forEach(function (key) {
        panels[key].hidden = key !== name;
      });
    }
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        var name = tab.getAttribute("data-mtab");
        if (panels[name]) {
          show(name);
        }
      });
    });
    var first = null;
    tabs.forEach(function (tab) {
      var name = tab.getAttribute("data-mtab");
      if (!first && panels[name] && !panels[name].hidden) {
        first = name;
      }
    });
    if (first) {
      show(first);
    }
  }

  function init() {
    initTabs();
    initVoicePanel();
    initMarketTabs();
  }

  if (typeof document !== "undefined" && document) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }
})();
