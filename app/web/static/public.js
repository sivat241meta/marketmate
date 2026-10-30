/* Shared public pages (Task 90): market result tabs (Best basket /
   Shops / Items). The homepage loads home.js instead, so this never
   double-binds there. Makes no network calls. */
(function () {
  "use strict";

  /* Task 122: the phone menu sheet is owned by popups.js (loaded on
     every public page through the shared header). Task 125: the old
     market search card is gone (the query pill opens the search
     pop-up), so the card tabs and voice-panel toggle went with it;
     voice lives in the pop-up (popups.js) and the panel composer. */

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
