// Marketplace homepage (Task 84, v12 Task 122): hearts, carousels,
// last search. The area chooser, phone menu and pop-ups moved to
// popups.js; the nearest-area math stays here for the node test.
//
// PRIVACY: the customer's coordinates never leave this phone. This file
// makes no network calls at all (no fetch, no XHR, no beacons).

(function () {
  "use strict";

  function toRad(deg) {
    return (deg * Math.PI) / 180;
  }

  function haversineKm(aLat, aLng, bLat, bLng) {
    var R = 6371;
    var dLat = toRad(bLat - aLat);
    var dLng = toRad(bLng - aLng);
    var s1 = Math.sin(dLat / 2);
    var s2 = Math.sin(dLng / 2);
    var a = s1 * s1
      + Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * s2 * s2;
    return 2 * R * Math.asin(Math.sqrt(a));
  }

  function num(value) {
    var parsed = parseFloat(value);
    return isNaN(parsed) ? null : parsed;
  }

  // Nearest named area to (lat, lng); tiles without coordinates are
  // skipped. Returns the area name or null when nothing qualifies.
  function nearestArea(areas, lat, lng) {
    var best = null;
    var bestKm = null;
    areas.forEach(function (area) {
      var aLat = num(area.lat);
      var aLng = num(area.lng);
      if (aLat === null || aLng === null) {
        return;
      }
      var km = haversineKm(lat, lng, aLat, aLng);
      if (bestKm === null || km < bestKm) {
        bestKm = km;
        best = area.name;
      }
    });
    return best;
  }

  if (typeof window !== "undefined") {
    window.MarketHome = {
      haversineKm: haversineKm,
      nearestArea: nearestArea,
    };
  }
  if (typeof document === "undefined") {
    return;
  }

  // Task 115: hearts (My list) + last search. Local only.
  var SAVE_KEY = "mm_saved_list";
  var LASTQ_KEY = "mm_last_q";

  function loadSaved() {
    try {
      var raw = window.localStorage
        ? window.localStorage.getItem(SAVE_KEY)
        : null;
      var parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (err) {
      return {};
    }
  }

  function storeSaved(saved) {
    try {
      if (window.localStorage) {
        window.localStorage.setItem(SAVE_KEY, JSON.stringify(saved));
      }
    } catch (err) { /* private mode: hearts just work once */ }
  }

  function toast(msg) {
    if (msg && window.Motion && window.Motion.toast) {
      window.Motion.toast(msg);
    }
  }

  function initHearts() {
    var btns = document.querySelectorAll("[data-heart]");
    if (!btns.length) {
      return;
    }
    var saved = loadSaved();
    btns.forEach(function (btn) {
      var key = btn.getAttribute("data-key") || "";
      if (key && saved[key]) {
        btn.classList.add("on");
        btn.setAttribute("aria-pressed", "true");
      }
      btn.addEventListener("click", function () {
        var on = btn.classList.toggle("on");
        btn.setAttribute("aria-pressed", on ? "true" : "false");
        var cur = loadSaved();
        if (on) {
          cur[key] = 1;
          toast(btn.getAttribute("data-saved"));
        } else {
          delete cur[key];
          toast(btn.getAttribute("data-removed"));
        }
        storeSaved(cur);
      });
    });
  }

  function initLastQ() {
    document.querySelectorAll("form[data-search-form]").forEach(
      function (form) {
        form.addEventListener("submit", function () {
          var input = form.querySelector("input[name=\"q\"]");
          try {
            if (input && window.localStorage) {
              window.localStorage.setItem(LASTQ_KEY, input.value || "");
            }
          } catch (err) { /* private mode: nothing remembered */ }
        });
      });
  }

  // Task 122: carousels — arrow buttons scroll one card, dots track
  // pages and jump. Transform-free (native scroll + snap); the dots
  // are plain buttons, so no-JS users still swipe.
  function initCarousels() {
    var reduce = window.matchMedia
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.querySelectorAll("[data-carousel]").forEach(function (box) {
      if (box.dataset.mmBound) {
        return;
      }
      box.dataset.mmBound = "1";
      var scope = box.parentNode || document;
      var prev = scope.querySelector
        ? scope.querySelector("[data-prev]")
        : null;
      var next = scope.querySelector
        ? scope.querySelector("[data-next]")
        : null;
      var dots = scope.querySelector
        ? scope.querySelector("[data-dots]")
        : null;

      function step() {
        var card = box.querySelector(":scope > *");
        if (!card) {
          return box.clientWidth;
        }
        var gap = 12;
        try {
          var cs = window.getComputedStyle(box);
          gap = parseFloat(cs.columnGap || cs.gap || "12") || 12;
        } catch (err) { /* default gap */ }
        return card.offsetWidth + gap;
      }

      function pages() {
        if (!box.scrollWidth || !box.clientWidth) {
          return 1;
        }
        return Math.max(1, Math.round(
          box.scrollWidth / box.clientWidth));
      }

      function current() {
        if (!box.clientWidth) {
          return 0;
        }
        return Math.min(pages() - 1, Math.round(
          box.scrollLeft / box.clientWidth));
      }

      function paint() {
        if (prev) {
          prev.disabled = box.scrollLeft <= 2;
        }
        if (next) {
          next.disabled = box.scrollLeft + box.clientWidth
            >= box.scrollWidth - 2;
        }
        if (dots) {
          var n = pages();
          var at = current();
          var kids = dots.children;
          if (kids.length !== n) {
            dots.innerHTML = "";
            for (var i = 0; i < n; i++) {
              (function (page) {
                var dot = document.createElement("button");
                dot.type = "button";
                dot.className = "cdot";
                dot.setAttribute("aria-label", "Page " + (page + 1));
                dot.addEventListener("click", function () {
                  box.scrollTo({
                    left: page * box.clientWidth,
                    behavior: reduce ? "auto" : "smooth",
                  });
                });
                dots.appendChild(dot);
              })(i);
            }
            kids = dots.children;
          }
          Array.prototype.forEach.call(kids, function (dot, i) {
            var on = i === at;
            dot.classList.toggle("on", on);
            if (on) {
              dot.setAttribute("aria-current", "true");
            } else {
              dot.removeAttribute("aria-current");
            }
          });
          dots.hidden = n < 2;
        }
      }

      function go(dir) {
        box.scrollBy({
          left: dir * step(),
          behavior: reduce ? "auto" : "smooth",
        });
      }

      if (prev) {
        prev.addEventListener("click", function () { go(-1); });
      }
      if (next) {
        next.addEventListener("click", function () { go(1); });
      }
      var ticking = false;
      box.addEventListener("scroll", function () {
        if (!ticking) {
          ticking = true;
          window.requestAnimationFrame(function () {
            paint();
            ticking = false;
          });
        }
      }, { passive: true });
      window.addEventListener("resize", paint);
      paint();
    });
  }

  // Task 127: the homepage white header slides down once the
  // hero has scrolled away (inner pages render .solid instead).
  function initStickybar() {
    var bar = document.querySelector("#site-header:not(.solid)");
    var hero = document.querySelector(".v13-hero");
    if (!bar || !hero || bar.dataset.mmBound) {
      return;
    }
    bar.dataset.mmBound = "1";
    var ticking = false;
    function update() {
      ticking = false;
      var past = window.scrollY
        > Math.max(hero.offsetHeight - 120, 200);
      bar.classList.toggle("on", past);
      bar.setAttribute("aria-hidden", past ? "false" : "true");
    }
    window.addEventListener("scroll", function () {
      if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(update);
      }
    }, { passive: true });
    window.addEventListener("resize", update);
    update();
  }

  // Task 127: the markets grid hides links past the seventh behind
  // Show more — from JS only, so no-JS users see every link.
  function initMarketsMore() {
    document.querySelectorAll("[data-markets]").forEach(function (grid) {
      if (grid.dataset.mmBound) {
        return;
      }
      grid.dataset.mmBound = "1";
      var btn = grid.querySelector("[data-markets-more]");
      var extra = grid.querySelector("[data-markets-extra]");
      if (!btn || !extra) {
        return;
      }
      extra.hidden = true;
      btn.hidden = false;
      btn.addEventListener("click", function () {
        var open = extra.hidden;
        extra.hidden = !open;
        btn.setAttribute("aria-expanded", open ? "true" : "false");
        var label = open
          ? btn.getAttribute("data-less")
          : btn.getAttribute("data-more");
        btn.childNodes[0].textContent = label + " ";
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initHearts();
    initLastQ();
    initCarousels();
    initStickybar();
    initMarketsMore();
  });
})();
