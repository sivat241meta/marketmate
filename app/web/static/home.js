// Marketplace homepage (Task 84): search tabs, mobile nav, area chooser.
//
// PRIVACY: the customer's coordinates never leave this phone. This file
// makes no network calls at all (no fetch, no XHR, no beacons); the
// "Detect my location" button only reads the area coordinates already
// rendered in data attributes and picks the nearest area in the browser.
// The choice is remembered in localStorage and applied as ?area=.

(function () {
  "use strict";

  var STORE_KEY = "mm_home_area";

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

  function remember(value) {
    try {
      if (window.localStorage) {
        window.localStorage.setItem(STORE_KEY, value);
      }
    } catch (err) { /* private mode: the choice just isn't kept */ }
  }

  function recalled() {
    try {
      return window.localStorage
        ? window.localStorage.getItem(STORE_KEY)
        : null;
    } catch (err) {
      return null;
    }
  }

  function goArea(name) {
    remember(name);
    window.location.assign("/?area=" + encodeURIComponent(name));
  }

  function currentAreaParam() {
    try {
      return new URLSearchParams(window.location.search).get("area") || "";
    } catch (err) {
      return "";
    }
  }

  function optionAreas(select) {
    var out = [];
    select.querySelectorAll("option[value]").forEach(function (opt) {
      if (!opt.value || opt.value === select.getAttribute("data-near-me")) {
        return;
      }
      out.push({
        name: opt.value,
        lat: opt.getAttribute("data-lat"),
        lng: opt.getAttribute("data-lng"),
      });
    });
    return out;
  }

  function tileAreas(root) {
    var out = [];
    root.querySelectorAll("[data-pick]").forEach(function (tile) {
      out.push({
        name: tile.getAttribute("data-pick"),
        lat: tile.getAttribute("data-area-lat"),
        lng: tile.getAttribute("data-area-lng"),
      });
    });
    return out;
  }

  function locate(success, failure) {
    if (!navigator.geolocation) {
      failure();
      return;
    }
    navigator.geolocation.getCurrentPosition(
      function (pos) {
        success(pos.coords.latitude, pos.coords.longitude);
      },
      function () { failure(); },
      { timeout: 8000, maximumAge: 600000 },
    );
  }

  function initTabs(form) {
    var input = form.querySelector("#hp-q");
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
  }

  function initMenu() {
    var btn = document.querySelector("[data-menu-open]");
    var sheet = document.getElementById("mobile-nav");
    if (!btn || !sheet) {
      return;
    }
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

  function initChooser() {
    var modal = document.getElementById("area-chooser");
    if (!modal) {
      return;
    }
    var openers = document.querySelectorAll("[data-chooser-open]");
    var search = modal.querySelector("[data-chooser-search]");
    var tiles = Array.prototype.slice.call(
      modal.querySelectorAll("[data-pick]"));
    var noMatch = modal.querySelector("[data-no-match]");
    var detectBtn = modal.querySelector("[data-detect]");
    var detectMsg = modal.querySelector("[data-detect-msg]");

    function open() {
      modal.hidden = false;
      if (search) {
        search.value = "";
        filter("");
        search.focus();
      }
    }
    function close() {
      modal.hidden = true;
    }
    function filter(text) {
      var needle = text.trim().toLowerCase();
      var visible = 0;
      tiles.forEach(function (tile) {
        var name = tile.getAttribute("data-name-lower") || "";
        var show = !needle || name.indexOf(needle) !== -1;
        tile.hidden = !show;
        if (show) {
          visible += 1;
        }
      });
      if (noMatch) {
        noMatch.hidden = visible !== 0;
      }
    }

    openers.forEach(function (btn) {
      btn.addEventListener("click", open);
    });
    modal.querySelectorAll("[data-close]").forEach(function (btn) {
      btn.addEventListener("click", close);
    });
    modal.addEventListener("click", function (event) {
      if (event.target === modal) {
        close();
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !modal.hidden) {
        close();
      }
    });
    if (search) {
      search.addEventListener("input", function () {
        filter(search.value);
      });
    }
    tiles.forEach(function (tile) {
      tile.addEventListener("click", function () {
        goArea(tile.getAttribute("data-pick") || "");
      });
    });
    modal.querySelectorAll("[data-skip]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        remember("all");
        close();
      });
    });
    if (detectBtn) {
      detectBtn.addEventListener("click", function () {
        var idle = detectBtn.innerHTML;
        detectBtn.disabled = true;
        detectBtn.textContent = detectBtn.getAttribute("data-detecting")
          || "…";
        if (detectMsg) {
          detectMsg.hidden = true;
        }
        locate(
          function (lat, lng) {
            var name = nearestArea(tileAreas(modal), lat, lng);
            detectBtn.disabled = false;
            detectBtn.innerHTML = idle;
            if (name) {
              goArea(name);
            } else if (detectMsg) {
              detectMsg.textContent = detectBtn.getAttribute("data-fail")
                || "";
              detectMsg.hidden = false;
            }
          },
          function () {
            detectBtn.disabled = false;
            detectBtn.innerHTML = idle;
            if (detectMsg) {
              detectMsg.textContent = detectBtn.getAttribute("data-fail")
                || "";
              detectMsg.hidden = false;
            }
          },
        );
      });
    }

    // First visit (no area chosen yet): open the chooser. A remembered
    // choice is applied as ?area=; an explicit ?area= wins and is kept.
    var param = currentAreaParam().trim();
    if (param) {
      remember(param);
    } else {
      var known = recalled();
      if (known && known !== "all") {
        window.location.assign("/?area=" + encodeURIComponent(known));
      } else if (!known && tiles.length) {
        open();
      }
    }
  }

  function initNearMe() {
    var select = document.getElementById("hp-area");
    var form = document.getElementById("search");
    if (!select || !form) {
      return;
    }
    var nearValue = select.getAttribute("data-near-me") || "nearme";
    select.addEventListener("change", function () {
      if (select.value !== nearValue) {
        return;
      }
      select.disabled = true;
      locate(
        function (lat, lng) {
          select.disabled = false;
          var name = nearestArea(optionAreas(select), lat, lng);
          if (name) {
            select.value = name;
          } else {
            select.value = "";
          }
        },
        function () {
          select.disabled = false;
          select.value = "";
        },
      );
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("search");
    if (form) {
      initTabs(form);
    }
    initMenu();
    initChooser();
    initNearMe();
  });
})();
