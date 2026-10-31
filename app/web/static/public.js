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

  // Task 127: the footer "Add to Home Screen" button. When the
  // browser offers an install prompt we use it; otherwise the
  // button shows the manual instructions (same hint the seller
  // shell documents) in a toast.
  // Task 150: on iPhones (no install prompt) the button shows the
  // short Share → Add to Home Screen instructions instead.
  var deferredPrompt = null;

  function isIos() {
    var ua = "";
    try {
      ua = window.navigator ? window.navigator.userAgent || "" : "";
    } catch (err) {
      ua = "";
    }
    return /iphone|ipad|ipod/i.test(ua);
  }

  function initInstall() {
    window.addEventListener("beforeinstallprompt", function (ev) {
      ev.preventDefault();
      deferredPrompt = ev;
    });
    document.querySelectorAll("[data-install]").forEach(function (btn) {
      if (btn.dataset.mmBound) {
        return;
      }
      btn.dataset.mmBound = "1";
      btn.addEventListener("click", function () {
        if (deferredPrompt) {
          deferredPrompt.prompt();
          if (deferredPrompt.userChoice
              && deferredPrompt.userChoice.then) {
            deferredPrompt.userChoice.then(function () {
              deferredPrompt = null;
            }).catch(function () {
              deferredPrompt = null;
            });
          } else {
            deferredPrompt = null;
          }
          return;
        }
        var hint = btn.getAttribute("data-hint") || "";
        if (isIos()) {
          hint = btn.getAttribute("data-ios-hint") || hint;
        }
        if (hint && window.Motion && window.Motion.toast) {
          window.Motion.toast(hint);
        }
      });
    });
  }

  function init() {
    initMarketTabs();
    initInstall();
  }

  if (typeof document !== "undefined" && document) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }
})();
