/* Task 149: priority+ public nav. The five header links never wrap;
   when the header row does not fit, the rightmost links move into the
   "More" dropdown one at a time until it fits (and move back out when
   the window grows). Measured live on load, resize (ResizeObserver),
   font load and window load, so every language fits every width.
   No network calls. */
(function () {
  "use strict";

  /* Direct-child links only — moved links live in [data-nav-more-list]. */
  function linksIn(nav) {
    var out = [];
    Array.prototype.forEach.call(nav.children, function (el) {
      if (el.tagName === "A" && el.hasAttribute("data-nav")) {
        out.push(el);
      }
    });
    return out;
  }

  function rowOverflows(row) {
    return row.scrollWidth > row.clientWidth + 1;
  }

  function setMoreState(more, list, btn) {
    var moved = list.children.length > 0;
    more.hidden = !moved;
    /* The active link keeps its underline: when it moves away, the
       indicator parks under the More button instead. */
    var activeMoved = false;
    Array.prototype.forEach.call(list.children, function (el) {
      if (el.classList && el.classList.contains("is-active")) {
        activeMoved = true;
      }
    });
    btn.classList.toggle("is-active", activeMoved);
    if (!moved) {
      btn.setAttribute("aria-expanded", "false");
      more.classList.remove("open");
    }
  }

  /* Fit one nav: everything back out, then the rightmost links in,
     one at a time, until the header row fits. */
  function fitNav(nav) {
    if (!nav || !nav.closest) {
      return 0;
    }
    var row = nav.closest(".topbar-in");
    var more = nav.querySelector("[data-nav-more]");
    if (!row || !more) {
      return 0;
    }
    var list = more.querySelector("[data-nav-more-list]");
    var btn = more.querySelector("[data-nav-more-btn]");
    if (!list || !btn) {
      return 0;
    }
    /* Below 1100px the nav hides and the phone sheet owns the links. */
    if (nav.offsetParent === null) {
      return 0;
    }
    while (list.children.length) {
      nav.insertBefore(list.children[0], more);
    }
    more.hidden = true;
    var moved = 0;
    var guard = linksIn(nav).length + 1;
    while (rowOverflows(row) && guard > 0) {
      guard -= 1;
      var links = linksIn(nav);
      if (!links.length) {
        break;
      }
      more.hidden = false;
      list.insertBefore(links[links.length - 1], list.firstChild);
      moved += 1;
    }
    setMoreState(more, list, btn);
    return moved;
  }

  function fitAll(root) {
    var scope = root || (typeof document !== "undefined" && document);
    if (!scope || !scope.querySelectorAll) {
      return;
    }
    Array.prototype.forEach.call(
      scope.querySelectorAll("[data-pnav]"), fitNav);
  }

  if (typeof window !== "undefined" && window) {
    window.MarketPNav = { fitNav: fitNav, fitAll: fitAll };
  }
  if (typeof document === "undefined" || !document) {
    return;
  }

  var scheduled = false;
  function schedule() {
    if (scheduled) {
      return;
    }
    scheduled = true;
    function run() {
      scheduled = false;
      fitAll(document);
    }
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(run);
    } else {
      window.setTimeout(run, 0);
    }
  }

  function init() {
    fitAll(document);
    if (window.ResizeObserver) {
      /* The row box rarely resizes (it fills the fixed wrap), but the
         nav box shrinks whenever a sibling (location, actions) grows,
         so both are watched. */
      var seen = [];
      Array.prototype.forEach.call(
        document.querySelectorAll("[data-pnav]"), function (nav) {
          var row = nav.closest ? nav.closest(".topbar-in") : null;
          [row, nav].forEach(function (el) {
            if (el && seen.indexOf(el) === -1) {
              seen.push(el);
            }
          });
        });
      var ro = new window.ResizeObserver(schedule);
      seen.forEach(function (el) {
        ro.observe(el);
      });
    }
    window.addEventListener("resize", schedule);
    window.addEventListener("load", schedule);
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(schedule);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
