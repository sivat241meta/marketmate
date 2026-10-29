// Market "Near me": on-device distance, sorted nearest-first.
//
// PRIVACY: the customer's coordinates never leave this phone. This file
// makes no network calls at all (no fetch, no XHR, no beacons); it only
// reads the shop coordinates already rendered in data-shop-lat/lng and
// computes a haversine distance in the browser.

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

  function formatKm(km) {
    if (km < 10) {
      return km.toFixed(1) + " km";
    }
    return String(Math.round(km)) + " km";
  }

  function shopCoords(el) {
    var la = parseFloat(el.getAttribute("data-shop-lat"));
    var ln = parseFloat(el.getAttribute("data-shop-lng"));
    if (isNaN(la) || isNaN(ln)) {
      return null;
    }
    return { lat: la, lng: ln };
  }

  function itemDistance(item, here) {
    var shop = shopCoords(item);
    if (shop === null) {
      return null;
    }
    return haversineKm(here.lat, here.lng, shop.lat, shop.lng);
  }

  function showDistances(here) {
    var items = document.querySelectorAll("[data-plan], [data-shop-row]");
    items.forEach(function (item) {
      var slot = item.querySelector("[data-distance]");
      if (!slot) {
        return;
      }
      var km = itemDistance(item, here);
      if (km === null) {
        slot.textContent = slot.getAttribute("data-unknown") || "";
      } else {
        slot.textContent = formatKm(km);
      }
      var wrap = slot.closest("[data-distance-wrap]");
      if (wrap) {
        wrap.hidden = false;
      }
    });
  }

  function sortContainer(container, itemSel, here, byDistance) {
    var items = Array.prototype.slice.call(
      container.querySelectorAll(":scope > " + itemSel));
    if (!items.length) {
      return;
    }
    items.sort(function (x, y) {
      if (byDistance) {
        var dx = itemDistance(x, here);
        var dy = itemDistance(y, here);
        if (dx === null && dy === null) {
          return orig(x) - orig(y);
        }
        if (dx === null) {
          return 1;
        }
        if (dy === null) {
          return -1;
        }
        if (dx !== dy) {
          return dx - dy;
        }
      }
      return orig(x) - orig(y);
    });
    items.forEach(function (item) {
      container.appendChild(item);
    });
  }

  function orig(el) {
    return parseInt(el.getAttribute("data-orig") || "0", 10) || 0;
  }

  function sortAll(here, byDistance) {
    document.querySelectorAll("[data-plans]").forEach(function (box) {
      sortContainer(box, "[data-plan]", here, byDistance);
    });
    document.querySelectorAll("[data-shop-list]").forEach(function (box) {
      sortContainer(box, "[data-shop-row]", here, byDistance);
    });
  }

  function init() {
    var btn = document.getElementById("near-me");
    var sortBox = document.getElementById("sort");
    var sortInput = document.getElementById("sort-value");
    var sortLinks = sortBox
      ? sortBox.querySelectorAll("[data-sort]")
      : [];
    var status = document.getElementById("near-me-status");
    if (!btn && !sortLinks.length) {
      return;
    }
    var here = null;
    function currentSort() {
      if (sortInput && sortInput.value) {
        return sortInput.value;
      }
      var on = sortBox && sortBox.querySelector("[data-sort].on");
      return on ? on.getAttribute("data-sort") : "total";
    }
    function setSort(mode) {
      if (sortInput) {
        sortInput.value = mode;
      }
      sortLinks.forEach(function (link) {
        link.classList.toggle(
          "on", link.getAttribute("data-sort") === mode);
      });
    }
    // The sort links are plain links without JS; with JS they sort in place.
    sortLinks.forEach(function (link) {
      link.addEventListener("click", function (ev) {
        ev.preventDefault();
        var mode = link.getAttribute("data-sort") || "total";
        setSort(mode);
        if (mode === "distance") {
          locate(function () {
            showDistances(here);
            sortAll(here, true);
          });
        } else {
          sortAll(here, false);
        }
      });
    });
    function locate(done) {
      if (here) {
        done();
        return;
      }
      if (!navigator.geolocation) {
        if (status) {
          status.textContent = "Location unavailable.";
        }
        return;
      }
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          here = { lat: pos.coords.latitude, lng: pos.coords.longitude };
          if (status) {
            status.textContent = "";
          }
          done();
        },
        function () {
          if (status) {
            status.textContent = "Location unavailable.";
          }
        },
        { maximumAge: 600000, timeout: 15000 },
      );
    }
    if (btn) {
      btn.addEventListener("click", function () {
        locate(function () {
          setSort("distance");
          showDistances(here);
          sortAll(here, true);
        });
      });
    }
    if (sortLinks.length && currentSort() === "distance") {
      locate(function () {
        showDistances(here);
        sortAll(here, true);
      });
    }
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }

  var api = { haversineKm: haversineKm, formatKm: formatKm };
  if (typeof globalThis !== "undefined") {
    globalThis.MarketNearMe = api;
  }
})();
