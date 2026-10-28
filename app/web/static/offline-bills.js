/* Offline tap-billing: queue bills in IndexedDB, sync on reconnect.
 *
 * - Tap form submits while offline are stored with a client_id (UUID) and
 *   the version id they were priced from, then POSTed to
 *   /e/{token}/bills/sync when the network is back.
 * - Live/voice controls carry data-needs-internet and show "needs internet"
 *   while offline.
 */
(function () {
  "use strict";

  var DB_NAME = "mm-offline";
  var STORE = "bills";

  function tokenFromPage() {
    var form = document.querySelector("[data-tap-form]");
    if (form && form.getAttribute("data-token")) {
      return form.getAttribute("data-token");
    }
    var match = window.location.pathname.match(/^\/e\/([^/]+)/);
    return match ? match[1] : null;
  }

  function openDb() {
    return new Promise(function (resolve, reject) {
      if (!("indexedDB" in window)) {
        reject(new Error("no indexeddb"));
        return;
      }
      var req = window.indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () {
        req.result.createObjectStore(STORE, { keyPath: "client_id" });
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function queuedBills(token) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var out = [];
        var tx = db.transaction(STORE, "readonly");
        var cursor = tx.objectStore(STORE).openCursor();
        cursor.onsuccess = function () {
          var item = cursor.result;
          if (!item) {
            resolve(out);
            return;
          }
          if (!token || item.value.token === token) {
            out.push(item.value);
          }
          item.continue();
        };
        cursor.onerror = function () { reject(cursor.error); };
      });
    });
  }

  function saveBill(entry) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, "readwrite");
        tx.objectStore(STORE).put(entry);
        tx.oncomplete = function () { resolve(entry); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function dropBills(clientIds) {
    if (!clientIds.length) {
      return Promise.resolve();
    }
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, "readwrite");
        var store = tx.objectStore(STORE);
        clientIds.forEach(function (id) { store.delete(id); });
        tx.oncomplete = function () { resolve(); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function bannerText(count) {
    var noun = count === 1 ? "bill" : "bills";
    return "Offline \u2013 " + count + " " + noun + " will sync when you're back online";
  }

  function refreshBanner() {
    var banner = document.querySelector("[data-offline-banner]");
    var label = document.querySelector("[data-offline-text]");
    if (!banner || !label) {
      return;
    }
    queuedBills(tokenFromPage()).then(function (queued) {
      if (!queued.length) {
        banner.hidden = true;
        return;
      }
      label.textContent = bannerText(queued.length);
      banner.hidden = false;
    }).catch(function () {
      banner.hidden = true;
    });
  }

  function refreshOnlineState() {
    var online = navigator.onLine !== false;
    document.querySelectorAll("[data-needs-internet]").forEach(function (el) {
      var hint = el.querySelector("[data-needs-internet-hint]");
      if (online) {
        el.removeAttribute("data-offline");
        if (hint) {
          hint.hidden = true;
        }
      } else {
        el.setAttribute("data-offline", "1");
        if (!hint) {
          hint = document.createElement("p");
          hint.setAttribute("data-needs-internet-hint", "1");
          hint.className = "muted";
          hint.textContent = "needs internet";
          el.appendChild(hint);
        } else {
          hint.hidden = false;
        }
      }
    });
    document.querySelectorAll("[data-live-order-mic], #rec-start").forEach(function (btn) {
      if ("disabled" in btn) {
        btn.disabled = !online;
      }
    });
  }

  function collectTapLines(form) {
    var lines = [];
    var data = new FormData(form);
    var indices = {};
    Array.from(data.keys()).forEach(function (key) {
      ["qty_", "amount_", "name_en_"].forEach(function (prefix) {
        if (key.indexOf(prefix) === 0) {
          indices[key.slice(prefix.length)] = true;
        }
      });
    });
    Object.keys(indices).forEach(function (index) {
      var name = String(data.get("name_en_" + index) || "").trim();
      if (!name) {
        return;
      }
      var amount = String(data.get("amount_" + index) || "").trim();
      if (amount) {
        lines.push({ name_en: name, amount: amount });
        return;
      }
      var qty = String(data.get("qty_" + index) || "").trim();
      if (!qty || qty === "0") {
        return;
      }
      lines.push({
        name_en: name,
        qty: qty,
        unit: String(data.get("unit_" + index) || "").trim() || null,
      });
    });
    return lines;
  }

  function syncNow() {
    var token = tokenFromPage();
    if (!token || navigator.onLine === false) {
      return Promise.resolve();
    }
    return queuedBills(token).then(function (queued) {
      if (!queued.length) {
        return null;
      }
      return fetch("/e/" + encodeURIComponent(token) + "/bills/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bills: queued }),
      }).then(function (resp) {
        if (!resp.ok) {
          return null;
        }
        return resp.json().then(function (body) {
          var done = (body.results || []).map(function (row) { return row.client_id; });
          return dropBills(done).then(refreshBanner);
        });
      });
    }).catch(function () {
      /* stay queued; the banner keeps the count */
    });
  }

  function uuid() {
    if (window.crypto && window.crypto.randomUUID) {
      return window.crypto.randomUUID();
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = Math.floor(Math.random() * 16);
      var v = c === "x" ? r : ((r & 0x3) | 0x8);
      return v.toString(16);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {
        /* offline support is best-effort */
      });
    }
    refreshOnlineState();
    refreshBanner();
    var token = tokenFromPage();
    if (token && navigator.onLine !== false) {
      // Warm the per-seller caches: today's price list + this page.
      fetch("/e/" + encodeURIComponent(token) + "/prices.json").catch(function () {});
      syncNow();
    }
    window.addEventListener("online", function () {
      refreshOnlineState();
      syncNow();
    });
    window.addEventListener("offline", refreshOnlineState);
    var form = document.querySelector("[data-tap-form]");
    if (form) {
      form.addEventListener("submit", function (event) {
        if (navigator.onLine !== false) {
          return;
        }
        event.preventDefault();
        var lines = collectTapLines(form);
        if (!lines.length) {
          return;
        }
        saveBill({
          client_id: uuid(),
          token: token,
          version_id: parseInt(form.getAttribute("data-version") || "0", 10) || null,
          lines: lines,
          customer_phone: null,
          created_at: new Date().toISOString(),
        }).then(function () {
          form.querySelectorAll('input[name^="qty_"]').forEach(function (input) {
            input.value = "0";
          });
          refreshBanner();
        }).catch(function () {
          /* storage full or blocked; leave the form as-is */
        });
      });
    }
  });
})();
