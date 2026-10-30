/* Task 115 motion: reveal on scroll, count-up, header shadow, toast.
   No libraries, no network. Gated by matchMedia for reduced motion. */
(function () {
  "use strict";
  if (typeof document === "undefined" || !document) {
    return;
  }
  var doc = document.documentElement;
  if (doc) {
    doc.classList.add("js");
  }
  var reduce = window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function stagger(root) {
    var kids = root.querySelectorAll(":scope > [data-reveal]");
    Array.prototype.forEach.call(kids, function (el, i) {
      el.style.setProperty("--rv", String(Math.min(i, 8)));
    });
  }
  Array.prototype.forEach.call(
    document.querySelectorAll("[data-reveal-group]"), stagger);

  var revealed = document.querySelectorAll("[data-reveal]");
  if (!revealed.length || reduce || !("IntersectionObserver" in window)) {
    Array.prototype.forEach.call(revealed, function (el) {
      el.classList.add("in");
    });
  } else {
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in");
          seen.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
    Array.prototype.forEach.call(revealed, function (el) {
      seen.observe(el);
    });
  }

  function countUp(el) {
    var end = parseInt(el.getAttribute("data-count") || "0", 10);
    if (reduce || !(end > 0)) {
      el.textContent = String(end);
      return;
    }
    var start = 0;
    var dur = 900;
    var t0 = null;
    function frame(now) {
      if (t0 === null) {
        t0 = now;
      }
      var p = Math.min((now - t0) / dur, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = String(Math.round(start + (end - start) * eased));
      if (p < 1) {
        window.requestAnimationFrame(frame);
      }
    }
    window.requestAnimationFrame(frame);
  }
  var counters = document.querySelectorAll("[data-count]");
  if (!counters.length) {
    /* nothing to count */
  } else if (reduce || !("IntersectionObserver" in window)) {
    Array.prototype.forEach.call(counters, countUp);
  } else {
    var watched = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          countUp(entry.target);
          watched.unobserve(entry.target);
        }
      });
    }, { threshold: 0.4 });
    Array.prototype.forEach.call(counters, function (el) {
      watched.observe(el);
    });
  }

  var heads = document.querySelectorAll(".hp-header, .hdr");
  function shadow() {
    Array.prototype.forEach.call(heads, function (head) {
      head.classList.toggle("scrolled", window.scrollY > 4);
    });
  }
  var ticking = false;
  window.addEventListener("scroll", function () {
    if (!ticking) {
      ticking = true;
      window.requestAnimationFrame(function () {
        shadow();
        ticking = false;
      });
    }
  }, { passive: true });
  shadow();

  function toast(msg) {
    if (!msg) {
      return;
    }
    var old = document.querySelector(".mtoast");
    if (old) {
      old.remove();
    }
    var tip = document.createElement("div");
    tip.className = "mtoast";
    tip.setAttribute("role", "status");
    tip.textContent = msg;
    document.body.appendChild(tip);
    window.setTimeout(function () {
      tip.classList.add("out");
      window.setTimeout(function () {
        tip.remove();
      }, 300);
    }, 2000);
  }
  window.Motion = window.Motion || {};
  window.Motion.toast = toast;
})();
