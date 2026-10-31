/* "Use my current location" for the v12 location drawer (Task 122).
   Wires [data-loc-detect]: reads the phone GPS once, picks the
   nearest area from the drawer's own coordinates, and navigates.
   No network calls at all — coordinates never leave this phone. */
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

  function nearestTile(tiles, lat, lng) {
    var best = null;
    var bestKm = null;
    tiles.forEach(function (tile) {
      var aLat = num(tile.getAttribute("data-area-lat"));
      var aLng = num(tile.getAttribute("data-area-lng"));
      if (aLat === null || aLng === null) {
        return;
      }
      var km = haversineKm(lat, lng, aLat, aLng);
      if (bestKm === null || km < bestKm) {
        bestKm = km;
        best = tile.getAttribute("data-pick");
      }
    });
    return best;
  }

  function goArea(name) {
    // One shared pick handler (Task 134): popups.js owns the
    // stay-or-go rules, so the GPS pick behaves exactly like a tile.
    if (window.MarketPopups
        && typeof window.MarketPopups.goArea === "function") {
      window.MarketPopups.goArea(name);
      return;
    }
    try {
      if (window.localStorage) {
        window.localStorage.setItem(STORE_KEY, JSON.stringify(name));
      }
    } catch (err) { /* private mode: nothing remembered */ }
    var path = window.location.pathname || "/";
    if (path === "/market") {
      var params = new URLSearchParams(window.location.search || "");
      if (name) {
        params.set("area", name);
      } else {
        params.delete("area");
      }
      window.location.assign("/market?" + params.toString());
    } else if (path === "/") {
      if (name) {
        window.location.assign("/?area=" + encodeURIComponent(name));
      } else {
        window.location.assign("/");
      }
    } else if (name && typeof document !== "undefined" && document) {
      // Off-homepage without popups.js: remember the pick and label
      // the header button; never navigate away.
      document.querySelectorAll("[data-loc-open]").forEach(
        function (btn) {
          if (btn.setAttribute) {
            btn.setAttribute("aria-label", name);
          }
        });
    }
  }

  function init() {
    var pop = document.getElementById("loc-drawer");
    if (!pop) {
      return;
    }
    var btn = pop.querySelector("[data-loc-detect]");
    var msg = pop.querySelector("[data-loc-msg]");
    if (!btn || btn.dataset.mmBound) {
      return;
    }
    btn.dataset.mmBound = "1";
    btn.addEventListener("click", function () {
      var idle = btn.innerHTML;
      var tiles = Array.prototype.slice.call(
        pop.querySelectorAll("[data-pick]"));
      function fail() {
        btn.disabled = false;
        btn.innerHTML = idle;
        if (msg) {
          msg.textContent = btn.getAttribute("data-fail") || "";
          msg.hidden = false;
        }
      }
      if (!navigator.geolocation) {
        fail();
        return;
      }
      btn.disabled = true;
      btn.textContent = btn.getAttribute("data-detecting") || "…";
      if (msg) {
        msg.hidden = true;
      }
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          var name = nearestTile(
            tiles, pos.coords.latitude, pos.coords.longitude);
          btn.disabled = false;
          btn.innerHTML = idle;
          if (name) {
            goArea(name);
          } else {
            fail();
          }
        },
        function () { fail(); },
        { timeout: 8000, maximumAge: 600000 },
      );
    });
  }

  // Task 134: hook for the node test, mirroring window.MarketHome.
  if (typeof window !== "undefined" && window) {
    window.MarketLocate = {
      goArea: goArea,
    };
  }

  if (typeof document !== "undefined" && document) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }
})();
