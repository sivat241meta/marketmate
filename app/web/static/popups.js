/* Shared v12 pop-ups (Task 122): one dialog manager (focus trap,
   Esc/backdrop close, scroll lock) driving the location drawer, the
   search pop-up and the filter pop-up, plus the phone menu sheet.
   Same-origin GETs to /market/suggest.json only (query + area name).
   GPS stays in locate.js, which makes no network calls at all. */
(function () {
  "use strict";

  var STORE_KEY = "mm_home_area";
  var RECENT_KEY = "mm_recent_q";
  var MAX_RECENT = 6;

  function esc(text) {
    return String(text === null || text === undefined ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function load(key, fallback) {
    try {
      var raw = window.localStorage ? window.localStorage.getItem(key) : null;
      if (raw === null || raw === undefined) {
        return fallback;
      }
      var parsed = JSON.parse(raw);
      return parsed === null || parsed === undefined ? fallback : parsed;
    } catch (err) {
      return fallback;
    }
  }

  function store(key, value) {
    try {
      if (window.localStorage) {
        window.localStorage.setItem(key, JSON.stringify(value));
      }
    } catch (err) { /* private mode: nothing remembered */ }
  }

  /* ---- dialog manager ---- */

  var openPop = null;
  var lastOpener = null;

  function focusables(root) {
    var els = root.querySelectorAll(
      "a[href], button:not([disabled]), input:not([disabled]), " +
      "select:not([disabled]), textarea:not([disabled]), [tabindex]");
    return Array.prototype.filter.call(els, function (el) {
      return !el.hidden && el.getAttribute("tabindex") !== "-1"
        && el.offsetParent !== null;
    });
  }

  function openPop2(pop, opener) {
    if (!pop || !pop.hidden) {
      return;
    }
    if (openPop && openPop !== pop) {
      closePop(openPop);
    }
    lastOpener = opener || null;
    pop.hidden = false;
    document.body.classList.add("mm-locked");
    openPop = pop;
    pop.dispatchEvent(new CustomEvent("mm-fill"));
    var box = pop.querySelector("[role=\"dialog\"]");
    var els = box ? focusables(box) : [];
    var input = box ? box.querySelector("input[type=\"search\"]") : null;
    if (input && els.indexOf(input) !== -1) {
      input.focus();
    } else if (els.length) {
      els[0].focus();
    }
  }

  function closePop(pop) {
    pop = pop || openPop;
    if (!pop || pop.hidden) {
      return;
    }
    pop.hidden = true;
    if (openPop === pop) {
      openPop = null;
    }
    if (!document.querySelector(".mm-pop:not([hidden])")) {
      document.body.classList.remove("mm-locked");
    }
    if (lastOpener && document.contains(lastOpener)) {
      lastOpener.focus();
      lastOpener = null;
    }
  }

  function initDialogs() {
    document.querySelectorAll(".mm-pop").forEach(function (pop) {
      if (pop.dataset.mmBound) {
        return;
      }
      pop.dataset.mmBound = "1";
      pop.querySelectorAll("[data-close]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          closePop(pop);
        });
      });
      pop.addEventListener("keydown", function (ev) {
        if (ev.key !== "Tab") {
          return;
        }
        var box = pop.querySelector("[role=\"dialog\"]");
        var els = box ? focusables(box) : [];
        if (!els.length) {
          return;
        }
        var first = els[0];
        var last = els[els.length - 1];
        if (ev.shiftKey && document.activeElement === first) {
          ev.preventDefault();
          last.focus();
        } else if (!ev.shiftKey && document.activeElement === last) {
          ev.preventDefault();
          first.focus();
        }
      });
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && openPop) {
        closePop(openPop);
      }
    });
  }

  function bindOpener(attr, id) {
    var pop = document.getElementById(id);
    if (!pop) {
      return null;
    }
    document.querySelectorAll("[" + attr + "]").forEach(function (btn) {
      if (btn.dataset.mmBound) {
        return;
      }
      btn.dataset.mmBound = "1";
      btn.addEventListener("click", function () {
        openPop2(pop, btn);
      });
    });
    return pop;
  }

  /* ---- phone menu sheet ---- */

  function initMenu() {
    // Task 127: the homepage has two openers (hero topbar + the
    // sticky bar) — every one of them drives the same sheet.
    var btns = document.querySelectorAll("[data-menu-open]");
    var sheet = document.getElementById("mobile-nav");
    if (!btns.length || !sheet) {
      return;
    }
    function setExpanded(open) {
      btns.forEach(function (btn) {
        btn.setAttribute("aria-expanded", open ? "true" : "false");
      });
    }
    btns.forEach(function (btn) {
      if (btn.dataset.mmBound) {
        return;
      }
      btn.dataset.mmBound = "1";
      btn.addEventListener("click", function () {
        var open = sheet.hidden;
        sheet.hidden = !open;
        setExpanded(open);
      });
    });
    if (sheet.dataset.mmBound) {
      return;
    }
    sheet.dataset.mmBound = "1";
    sheet.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        sheet.hidden = true;
        setExpanded(false);
      });
    });
  }

  /* ---- language dropdown ---- */

  function initLangDrop() {
    // Task 127: the EN button toggles its menu; Esc or an outside
    // click closes it. The menu items are the same cookie buttons
    // / ?lang= links as the v12 segment, so they keep working
    // with no extra code.
    var drops = document.querySelectorAll("[data-lang-drop]");
    if (!drops.length) {
      return;
    }
    function closeAll(except) {
      drops.forEach(function (drop) {
        if (drop === except) {
          return;
        }
        var menu = drop.querySelector("[data-lang-menu]");
        var btn = drop.querySelector("[data-lang-btn]");
        if (menu) {
          menu.hidden = true;
        }
        if (btn) {
          btn.setAttribute("aria-expanded", "false");
        }
      });
    }
    drops.forEach(function (drop) {
      if (drop.dataset.mmBound) {
        return;
      }
      drop.dataset.mmBound = "1";
      var btn = drop.querySelector("[data-lang-btn]");
      var menu = drop.querySelector("[data-lang-menu]");
      if (!btn || !menu) {
        return;
      }
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var open = menu.hidden;
        closeAll(drop);
        menu.hidden = !open;
        btn.setAttribute("aria-expanded", open ? "true" : "false");
      });
      menu.addEventListener("click", function (ev) {
        ev.stopPropagation();
      });
      menu.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") {
          menu.hidden = true;
          btn.setAttribute("aria-expanded", "false");
          btn.focus();
        }
      });
    });
    document.addEventListener("click", function () {
      closeAll(null);
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        closeAll(null);
      }
    });
  }

  /* ---- location drawer ---- */

  function goArea(name) {
    store(STORE_KEY, name);
    var path = window.location.pathname || "/";
    if (path === "/market") {
      var params = new URLSearchParams(window.location.search || "");
      if (name) {
        params.set("area", name);
      } else {
        params.delete("area");
      }
      window.location.assign("/market?" + params.toString());
    } else if (name) {
      window.location.assign("/?area=" + encodeURIComponent(name));
    } else {
      window.location.assign("/");
    }
  }

  function currentAreaParam() {
    try {
      return new URLSearchParams(window.location.search).get("area") || "";
    } catch (err) {
      return "";
    }
  }

  function renderTiles(list, areas) {
    list.innerHTML = areas.map(function (area) {
      var photo = area.photo
        ? "<span class=\"tile-photo\"><img src=\"" + esc(area.photo) +
          "\" alt=\"\" loading=\"lazy\" width=\"200\" height=\"150\"></span>"
        : "<span class=\"tile-ic\">◉</span>";
      return "<button type=\"button\" class=\"choose-tile\" data-pick=\"" +
        esc(area.name) + "\" data-name-lower=\"" +
        esc(String(area.name || "").toLowerCase()) + "\">" + photo +
        "<b>" + esc(area.name) + "</b>" +
        "<small class=\"muted\">" + esc(area.shops) + "</small></button>";
    }).join("");
    return Array.prototype.slice.call(list.querySelectorAll("[data-pick]"));
  }

  function initLocation() {
    var pop = document.getElementById("loc-drawer");
    if (!pop) {
      return;
    }
    var list = pop.querySelector("[data-loc-list]");
    var search = pop.querySelector("[data-loc-search]");
    var none = pop.querySelector("[data-loc-none]");
    /* The detect button is wired by locate.js (no network there). */
    var tiles = list
      ? Array.prototype.slice.call(list.querySelectorAll("[data-pick]"))
      : [];

    function filter(text) {
      var needle = (text || "").trim().toLowerCase();
      var visible = 0;
      tiles.forEach(function (tile) {
        var name = tile.getAttribute("data-name-lower") || "";
        var show = !needle || name.indexOf(needle) !== -1;
        tile.hidden = !show;
        if (show) {
          visible += 1;
        }
      });
      if (none) {
        none.hidden = visible !== 0;
      }
    }

    function bindTiles() {
      tiles.forEach(function (tile) {
        if (tile.dataset.mmBound) {
          return;
        }
        tile.dataset.mmBound = "1";
        tile.addEventListener("click", function () {
          goArea(tile.getAttribute("data-pick") || "");
        });
      });
    }

    bindTiles();
    if (search) {
      search.addEventListener("input", function () {
        filter(search.value);
      });
    }

    // Pages without server tiles (shop, orders…) fill the drawer from
    // the suggest endpoint the first time it opens.
    var filled = tiles.length > 0;
    if (list && !filled) {
      var url = list.getAttribute("data-areas-url");
      pop.addEventListener("mm-fill", function handler() {
        pop.removeEventListener("mm-fill", handler);
        if (!url || typeof fetch === "undefined") {
          return;
        }
        fetch(url + "?q=", { headers: { Accept: "application/json" } })
          .then(function (resp) {
            return resp.ok ? resp.json() : null;
          })
          .then(function (data) {
            if (!data || !data.areas || !data.areas.length) {
              return;
            }
            tiles = renderTiles(list, data.areas);
            bindTiles();
            if (search) {
              filter(search.value);
            }
          })
          .catch(function () { /* drawer keeps working empty */ });
      });
    }

    // First visit (no area chosen yet): a remembered choice is applied
    // as ?area=; an explicit ?area= wins and is kept.
    var param = currentAreaParam().trim();
    if (param) {
      store(STORE_KEY, param);
    } else {
      var known = load(STORE_KEY, null);
      if (known && known !== "all") {
        window.location.assign("/?area=" + encodeURIComponent(known));
      } else if (!known && tiles.length && !openPop) {
        openPop2(pop, null);
      }
    }
  }

  /* ---- search pop-up ---- */

  function initSearch() {
    var pop = document.getElementById("search-pop");
    if (!pop) {
      return;
    }
    var form = pop.querySelector("[data-search-form]");
    var input = pop.querySelector("[data-search-input]");
    var live = pop.querySelector("[data-live]");
    var liveNone = pop.querySelector("[data-live-none]");
    var recentWrap = pop.querySelector("[data-recent-wrap]");
    var recentBox = pop.querySelector("[data-recent]");
    var popularBox = pop.querySelector("[data-popular]");
    var timer = null;

    function renderRecent() {
      if (!recentBox || !recentWrap) {
        return;
      }
      var items = load(RECENT_KEY, []);
      if (!items.length) {
        recentWrap.hidden = true;
        return;
      }
      recentWrap.hidden = false;
      recentBox.innerHTML = items.map(function (term) {
        return "<a class=\"chip\" href=\"/market?q=" +
          encodeURIComponent(term) + "\">" + esc(term) + "</a>";
      }).join("");
    }

    function fillPopular() {
      if (!popularBox) {
        return;
      }
      var grid = popularBox.querySelector(".mm-pop-grid");
      if (!grid || grid.children.length || typeof fetch === "undefined"
          || !input) {
        return;
      }
      var url = input.getAttribute("data-suggest-url");
      if (!url) {
        return;
      }
      fetch(url + "?q=", { headers: { Accept: "application/json" } })
        .then(function (resp) {
          return resp.ok ? resp.json() : null;
        })
        .then(function (data) {
          if (!data || !data.popular || !data.popular.length) {
            popularBox.hidden = true;
            return;
          }
          grid.innerHTML = data.popular.map(function (item) {
            var img = item.photo
              ? "<img src=\"" + esc(item.photo) +
                "\" alt=\"\" loading=\"lazy\" width=\"96\" height=\"96\">"
              : "<span class=\"nophoto\" aria-hidden=\"true\">" +
                esc(String(item.name || "?").slice(0, 1)) + "</span>";
            return "<a class=\"pop-circle\" href=\"/market?q=" +
              encodeURIComponent(item.name || "") + "\">" + img +
              "<span>" + esc(item.name) + "</span></a>";
          }).join("");
        })
        .catch(function () {
          popularBox.hidden = true;
        });
    }

    function renderLive(data) {
      if (!live) {
        return;
      }
      var items = (data && data.items) || [];
      var shops = (data && data.shops) || [];
      if (!items.length && !shops.length) {
        live.hidden = true;
        live.innerHTML = "";
        if (liveNone) {
          liveNone.hidden = false;
        }
        return;
      }
      if (liveNone) {
        liveNone.hidden = true;
      }
      var labels = {
        items: input.getAttribute("data-items") || "Items",
        shops: input.getAttribute("data-shops") || "Shops",
      };
      var html = "";
      if (items.length) {
        html += "<p class=\"mm-row-head\"><span>" + esc(labels.items) +
          "</span></p><div class=\"mm-live-list\">" + items.map(
            function (item) {
              return "<a class=\"mm-live-row\" href=\"/s/" +
                encodeURIComponent(item.slug || "") + "\"><span>" +
                esc(item.name) + "</span><span class=\"muted\">" +
                esc(item.price || "") + " · " + esc(item.shop || "") +
                "</span></a>";
            }).join("") + "</div>";
      }
      if (shops.length) {
        html += "<p class=\"mm-row-head\"><span>" + esc(labels.shops) +
          "</span></p><div class=\"mm-live-list\">" + shops.map(
            function (shop) {
              return "<a class=\"mm-live-row\" href=\"/s/" +
                encodeURIComponent(shop.slug || "") + "\"><span>" +
                esc(shop.name) + "</span><span class=\"muted\">" +
                esc(shop.area || "") + "</span></a>";
            }).join("") + "</div>";
      }
      live.innerHTML = html;
      live.hidden = false;
    }

    function lookup(term) {
      if (!input || typeof fetch === "undefined") {
        return;
      }
      var url = input.getAttribute("data-suggest-url");
      if (!url) {
        return;
      }
      var area = input.getAttribute("data-area") || "";
      fetch(url + "?q=" + encodeURIComponent(term) +
        (area ? "&area=" + encodeURIComponent(area) : ""),
        { headers: { Accept: "application/json" } })
        .then(function (resp) {
          return resp.ok ? resp.json() : null;
        })
        .then(function (data) {
          if ((input.value || "").trim() !== term) {
            return;
          }
          renderLive(data);
        })
        .catch(function () { /* typing keeps working offline */ });
    }

    if (input) {
      input.addEventListener("input", function () {
        var term = (input.value || "").trim();
        var idle = term === "";
        if (live) {
          live.hidden = true;
          live.innerHTML = "";
        }
        if (liveNone) {
          liveNone.hidden = true;
        }
        if (recentWrap) {
          recentWrap.hidden = !idle || !load(RECENT_KEY, []).length;
        }
        if (popularBox) {
          popularBox.hidden = !idle;
        }
        if (timer) {
          window.clearTimeout(timer);
          timer = null;
        }
        if (!idle) {
          timer = window.setTimeout(function () {
            lookup(term);
          }, 180);
        }
      });
    }
    if (form) {
      form.addEventListener("submit", function () {
        var term = input ? (input.value || "").trim() : "";
        if (!term) {
          return;
        }
        var items = load(RECENT_KEY, []).filter(function (old) {
          return old !== term;
        });
        items.unshift(term);
        store(RECENT_KEY, items.slice(0, MAX_RECENT));
      });
    }
    var clearBtn = pop.querySelector("[data-recent-clear]");
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        store(RECENT_KEY, []);
        renderRecent();
      });
    }

    // Prefill from the page query (market) or the URL, then show
    // recent + popular until the customer types.
    var observer = new MutationObserver(function () {
      if (pop.hidden) {
        return;
      }
      if (input && !input.value) {
        var pageQ = document.getElementById("market-q");
        var term = pageQ ? pageQ.value : "";
        if (!term) {
          try {
            term = new URLSearchParams(window.location.search).get("q")
              || "";
          } catch (err) {
            term = "";
          }
        }
        input.value = term;
        if (term.trim()) {
          lookup(term.trim());
        }
      }
      renderRecent();
      fillPopular();
    });
    observer.observe(pop, { attributes: true, attributeFilter: ["hidden"] });
    renderRecent();
  }

  /* ---- filter pop-up ---- */

  function syncChips(form) {
    form.querySelectorAll(".chip-row").forEach(function (row) {
      row.querySelectorAll("input").forEach(function (control) {
        var label = control.closest("label");
        if (label) {
          label.classList.toggle("on", !!control.checked);
        }
      });
    });
  }

  function activeFilterCount() {
    var params;
    try {
      params = new URLSearchParams(window.location.search || "");
    } catch (err) {
      return 0;
    }
    var n = 0;
    var sort = params.get("sort") || "total";
    if (sort !== "total") {
      n += 1;
    }
    if ((params.get("open_now") || "0") === "1") {
      n += 1;
    }
    if ((params.get("area") || "").trim()) {
      n += 1;
    }
    if ((params.get("budget") || "").trim()) {
      n += 1;
    }
    if ((params.get("cat") || "").trim()) {
      n += 1;
    }
    return n;
  }

  function refreshFilterBadges() {
    var n = activeFilterCount();
    document.querySelectorAll("[data-filter-count]").forEach(
      function (badge) {
        badge.textContent = n > 9 ? "9+" : String(n);
        badge.hidden = n === 0;
      });
  }

  function initFilter() {
    var pop = document.getElementById("filter-pop");
    if (!pop) {
      refreshFilterBadges();
      return;
    }
    var form = pop.querySelector("[data-filter-form]");
    if (form) {
      syncChips(form);
      form.addEventListener("change", function () {
        syncChips(form);
      });
      var clear = form.querySelector("[data-filter-clear]");
      if (clear) {
        clear.addEventListener("click", function () {
          form.querySelectorAll("input[type=\"checkbox\"]").forEach(
            function (box) {
              box.checked = false;
            });
          form.querySelectorAll("input[type=\"radio\"]").forEach(
            function (radio) {
              if (radio.name === "sort") {
                radio.checked = radio.value === "total";
              } else {
                radio.checked = radio.value === "";
              }
            });
          syncChips(form);
        });
      }
    }
    refreshFilterBadges();
  }

  /* Task 124: the search pop-up mic reveals the voice+text composer
     (same /market/voice action as the Find-a-shop voice panel).
     Task 125: openers carrying data-search-voice (the homepage
     banner's voice slide) open the pop-up with voice already shown. */
  function initVoice() {
    document.querySelectorAll("[data-voice-toggle]").forEach(
      function (btn) {
        var target = btn.getAttribute("aria-controls");
        var panel = target ? document.getElementById(target) : null;
        if (!panel) {
          return;
        }
        btn.addEventListener("click", function () {
          panel.hidden = !panel.hidden;
          btn.setAttribute("aria-expanded",
            panel.hidden ? "false" : "true");
        });
      });
    document.querySelectorAll("[data-search-open][data-search-voice]")
      .forEach(function (btn) {
        btn.addEventListener("click", function () {
          var panel = document.getElementById("search-voice");
          if (panel) {
            panel.hidden = false;
          }
          var toggle = document.querySelector("[data-voice-toggle]");
          if (toggle) {
            toggle.setAttribute("aria-expanded", "true");
          }
        });
      });
  }

  /* Task 125: the header More dropdown toggles on click for touch
     users (CSS also opens it on hover/focus-within). */
  function initMore() {
    var btn = document.querySelector("[data-nav-more-btn]");
    var wrap = document.querySelector("[data-nav-more]");
    if (!btn || !wrap || btn.dataset.mmBound) {
      return;
    }
    btn.dataset.mmBound = "1";
    function set(open) {
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      wrap.classList.toggle("open", open);
    }
    btn.addEventListener("click", function () {
      set(btn.getAttribute("aria-expanded") !== "true");
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        set(false);
      }
    });
    document.addEventListener("click", function (ev) {
      if (!wrap.contains(ev.target)) {
        set(false);
      }
    });
  }

  function init() {
    initDialogs();
    initMenu();
    initLangDrop();
    bindOpener("data-loc-open", "loc-drawer");
    bindOpener("data-search-open", "search-pop");
    bindOpener("data-filter-open", "filter-pop");
    bindOpener("data-shopsearch-open", "shopsearch-pop");
    initLocation();
    initSearch();
    initFilter();
    initVoice();
    initMore();
  }

  if (typeof document !== "undefined" && document) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }
})();
