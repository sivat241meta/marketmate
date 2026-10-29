/* My orders & shops (Task 60): this phone's own lists in localStorage.

   Customer pages record shop visits and sent orders (max 30, newest
   first); /my renders them with the live status from status.json.
   Nothing is stored on the server. */
(function () {
  "use strict";

  var SHOPS_KEY = "mm_my_shops";
  var ORDERS_KEY = "mm_my_orders";
  var MAX = 30;

  function load(key) {
    try {
      var raw = window.localStorage.getItem(key);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (err) {
      return [];
    }
  }

  function store(key, list) {
    try {
      window.localStorage.setItem(key, JSON.stringify(list.slice(0, MAX)));
    } catch (err) { /* private mode: lists just work once */ }
  }

  function rememberShop(slug, name, area) {
    if (!slug) {
      return;
    }
    var list = load(SHOPS_KEY).filter(function (entry) {
      return entry.slug !== slug;
    });
    list.unshift({ slug: slug, name: name || "", area: area || "" });
    store(SHOPS_KEY, list);
  }

  function rememberOrder(entry) {
    if (!entry || !entry.token) {
      return;
    }
    var list = load(ORDERS_KEY).filter(function (prior) {
      return prior.token !== entry.token;
    });
    list.unshift({
      token: entry.token,
      shop: entry.shop || "",
      number: entry.number || "",
      total: entry.total || "",
      date: entry.date || "",
    });
    store(ORDERS_KEY, list);
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) {
      node.className = cls;
    }
    if (text !== undefined && text !== null) {
      node.textContent = text;
    }
    return node;
  }

  function uiLang() {
    var lang = (document.documentElement
      && document.documentElement.lang) || "en";
    return (lang === "ta" || lang === "hi") ? lang : "en";
  }

  function currentLabel(steps, fallback) {
    var label = fallback || "";
    (steps || []).forEach(function (step) {
      if (step.current) {
        label = step.label || label;
      }
    });
    return label;
  }

  function renderMy(page) {
    var ordersBox = page.querySelector("[data-my-orders]");
    var shopsBox = page.querySelector("[data-my-shops]");
    var emptyOrders = page.getAttribute("data-empty-orders") || "";
    var emptyShops = page.getAttribute("data-empty-shops") || "";
    var orderPattern = page.getAttribute("data-order-pattern")
      || "Order #{n}";
    var findShop = page.getAttribute("data-find-shop") || "Find a shop";
    var openLabel = page.getAttribute("data-open-label") || "Open";

    function emptyCard(box, text) {
      var card = el("div", "card hp-empty");
      card.appendChild(el("p", "muted", text));
      var actions = el("p", "card-actions");
      var cta = el("a", "pill cta", findShop);
      cta.setAttribute("href", "/market");
      actions.appendChild(cta);
      card.appendChild(actions);
      box.appendChild(card);
    }

    function render() {
      var orders = load(ORDERS_KEY);
      var shops = load(SHOPS_KEY);
      if (ordersBox) {
        ordersBox.innerHTML = "";
        if (!orders.length) {
          emptyCard(ordersBox, emptyOrders);
        }
        orders.forEach(function (entry) {
          var card = el("article", "my-card");
          var top = el("div", "my-card-top");
          var title = orderPattern.split("{n}").join(
            String(entry.number));
          if (entry.shop) {
            title += " · " + entry.shop;
          }
          top.appendChild(el("p", "my-card-title", title));
          var pill = el("span", "pill pill-info", "");
          top.appendChild(pill);
          card.appendChild(top);
          var sub = entry.total || "";
          if (entry.date) {
            sub += (sub ? " · " : "") + entry.date;
          }
          if (sub) {
            card.appendChild(el("p", "my-card-sub", sub));
          }
          var actions = el("div", "my-card-actions");
          var open = el("a", "pill cta sm", openLabel);
          open.setAttribute("href", "/q/" + entry.token);
          actions.appendChild(open);
          card.appendChild(actions);
          ordersBox.appendChild(card);
          fetch("/q/" + entry.token + "/status.json?lang=" + uiLang(),
            { headers: { Accept: "application/json" } }).then(
            function (resp) {
              return resp.ok ? resp.json() : null;
            }).then(function (data) {
            if (data && data.steps) {
              pill.textContent = currentLabel(data.steps, data.status);
              if (data.total_fmt) {
                card.insertBefore(
                  el("p", "my-card-sub money", data.total_fmt), actions);
              }
            } else {
              pill.remove();
            }
          }).catch(function () {
            pill.remove();
          });
        });
      }
      if (shopsBox) {
        shopsBox.innerHTML = "";
        if (!shops.length) {
          emptyCard(shopsBox, emptyShops);
        }
        shops.forEach(function (entry) {
          var card = el("article", "my-card");
          card.appendChild(
            el("p", "my-card-title", entry.name || entry.slug));
          if (entry.area) {
            card.appendChild(el("p", "my-card-sub", entry.area));
          }
          var actions = el("div", "my-card-actions");
          var open = el("a", "pill cta sm", openLabel);
          open.setAttribute("href", "/s/" + entry.slug);
          actions.appendChild(open);
          card.appendChild(actions);
          shopsBox.appendChild(card);
        });
      }
    }

    var clearBtn = page.querySelector("[data-my-clear]");
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        store(ORDERS_KEY, []);
        store(SHOPS_KEY, []);
        render();
      });
    }
    render();
  }

  function init() {
    if (typeof document === "undefined" || !document) {
      return;
    }
    var visit = document.querySelector("[data-shop-visit]");
    if (visit) {
      rememberShop(visit.getAttribute("data-slug"),
        visit.getAttribute("data-name"), visit.getAttribute("data-area"));
    }
    var record = document.querySelector("[data-order-record]");
    if (record) {
      rememberOrder({
        token: record.getAttribute("data-token"),
        shop: record.getAttribute("data-shop"),
        number: record.getAttribute("data-number"),
        total: record.getAttribute("data-total"),
        date: record.getAttribute("data-date"),
      });
    }
    var page = document.querySelector("[data-my-page]");
    if (page) {
      renderMy(page);
    }
  }

  if (typeof document !== "undefined" && document) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }
})();
