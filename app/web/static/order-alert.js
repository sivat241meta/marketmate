/* New-order alert for sellers (Task 60): poll pending.json, badge the
   Orders nav, banner + beep when latest_id grows.

   Polls every 20 s, pauses while the tab is hidden, and backs off when
   offline or failing. The beep uses WebAudio (no file) and only plays
   after the seller has tapped the page once; the sound toggle is
   remembered in localStorage.
*/
(function () {
  "use strict";

  var BASE_MS = 20000;
  var MAX_MS = 300000;
  var SOUND_KEY = "mm_sound_on";

  function shouldAlert(prevId, nextId) {
    if (nextId === null || nextId === undefined) {
      return false;
    }
    if (prevId === null || prevId === undefined) {
      return true;
    }
    return Number(nextId) > Number(prevId);
  }

  function soundOn() {
    try {
      if (typeof localStorage === "undefined" || !localStorage) {
        return true;
      }
      return localStorage.getItem(SOUND_KEY) !== "off";
    } catch (err) {
      return true;
    }
  }

  function init() {
    if (typeof document === "undefined" || !document) {
      return;
    }
    var banner = document.querySelector("[data-order-banner]");
    if (!banner) {
      return;
    }
    var url = banner.getAttribute("data-pending-url") || "";
    var template = banner.getAttribute("data-alert-template")
      || "New order #{id} · {total}";
    var viewLabel = banner.getAttribute("data-alert-view") || "View";
    var orderBase = banner.getAttribute("data-order-base") || "";
    if (!url) {
      return;
    }
    var badges = Array.prototype.slice.call(
      document.querySelectorAll("[data-orders-badge]"));
    var bannerText = banner.querySelector("[data-order-banner-text]");
    var bannerLink = banner.querySelector("[data-order-banner-link]");
    var baseTitle = (typeof document.title === "string" ? document.title : "")
      .replace(/^\(\d+\)\s*/, "");
    var audioCtx = null;
    var timer = null;
    var failures = 0;
    var prevId = null;
    var started = false;
    var stopped = false;

    function wireSoundToggle() {
      var buttons = document.querySelectorAll("[data-sound-toggle]");
      Array.prototype.forEach.call(buttons, function (btn) {
        var onLabel = btn.getAttribute("data-sound-on") || "Sound on";
        var offLabel = btn.getAttribute("data-sound-off") || "Sound off";
        function render() {
          var on = soundOn();
          btn.textContent = on ? onLabel : offLabel;
          btn.setAttribute("aria-pressed", on ? "true" : "false");
        }
        btn.addEventListener("click", function () {
          try {
            if (typeof localStorage !== "undefined" && localStorage) {
              localStorage.setItem(SOUND_KEY, soundOn() ? "off" : "on");
            }
          } catch (err) { /* private mode: toggle just works once */ }
          render();
        });
        render();
      });
    }

    function ensureAudio() {
      try {
        if (typeof window === "undefined" || !window) {
          return null;
        }
        var AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) {
          return null;
        }
        if (!audioCtx) {
          audioCtx = new AC();
        }
        if (audioCtx.state === "suspended") {
          audioCtx.resume();
        }
        return audioCtx;
      } catch (err) {
        return null;
      }
    }

    function beep() {
      if (!soundOn()) {
        return;
      }
      var ctx = ensureAudio();
      if (!ctx) {
        return;
      }
      try {
        var osc = ctx.createOscillator();
        var gain = ctx.createGain();
        osc.type = "sine";
        osc.frequency.value = 880;
        gain.gain.setValueAtTime(0.001, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.5, ctx.currentTime + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.45);
      } catch (err) { /* no sound on this device */ }
    }

    function buzz() {
      try {
        if (typeof navigator !== "undefined" && navigator
            && typeof navigator.vibrate === "function") {
          navigator.vibrate(200);
        }
      } catch (err) { /* vibration unsupported */ }
    }

    function updateBadges(count) {
      badges.forEach(function (badge) {
        badge.textContent = String(count);
        // Task 61: the home count tile keeps its server-rendered zero.
        var keepZero = badge.dataset && ("ordersKeepZero" in badge.dataset);
        badge.hidden = count <= 0 && !keepZero;
      });
    }

    function updateTitle(count) {
      if (typeof document.title !== "string") {
        return;
      }
      document.title = count > 0
        ? "(" + count + ") " + baseTitle
        : baseTitle;
    }

    function showBanner(data) {
      var orders = (data && data.orders) || [];
      var latest = null;
      orders.forEach(function (entry) {
        if (!latest || Number(entry.id) > Number(latest.id)) {
          latest = entry;
        }
      });
      if (!latest) {
        return;
      }
      var text = template.split("{id}").join(String(latest.id))
        .split("{total}").join(latest.total || "");
      if (bannerText) {
        bannerText.textContent = text;
      }
      if (bannerLink) {
        bannerLink.textContent = viewLabel;
        bannerLink.setAttribute("href", orderBase + "/" + latest.id);
      }
      banner.hidden = false;
    }

    function schedule(ms) {
      if (timer) {
        clearTimeout(timer);
      }
      timer = setTimeout(poll, ms);
    }

    function backoff() {
      failures += 1;
      schedule(Math.min(MAX_MS, BASE_MS * Math.pow(2, failures)));
    }

    function poll() {
      if (stopped || document.hidden) {
        return;
      }
      if (typeof navigator !== "undefined" && navigator
          && navigator.onLine === false) {
        backoff();
        return;
      }
      fetch(url, { headers: { Accept: "application/json" } }).then(
        function (resp) {
          if (resp.status === 403 || resp.status === 404) {
            stopped = true;
            return null;
          }
          if (!resp.ok) {
            throw new Error("bad status " + resp.status);
          }
          return resp.json();
        }).then(function (data) {
        if (!data) {
          return;
        }
        failures = 0;
        var nextId = (data.latest_id === undefined) ? null : data.latest_id;
        var count = (typeof data.new === "number") ? data.new : 0;
        updateBadges(count);
        updateTitle(count);
        if (started && shouldAlert(prevId, nextId)) {
          showBanner(data);
          beep();
          buzz();
        }
        prevId = nextId;
        started = true;
        schedule(BASE_MS);
      }).catch(function () {
        backoff();
      });
    }

    document.addEventListener("pointerdown", function unlock() {
      ensureAudio();
    }, { once: true });
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        if (timer) {
          clearTimeout(timer);
        }
      } else if (!stopped) {
        poll();
      }
    });
    if (typeof window !== "undefined" && window
        && typeof window.addEventListener === "function") {
      window.addEventListener("online", function () {
        if (!stopped) {
          failures = 0;
          poll();
        }
      });
    }
    wireSoundToggle();
    poll();
  }

  if (typeof document !== "undefined" && document) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }

  if (typeof module !== "undefined" && module && module.exports) {
    module.exports = { shouldAlert: shouldAlert };
  }
})();
