/* MarketMate service worker: offline tap-billing shell.
 *
 * Caches the app shell (CSS, JS, fonts, icons) on install, and per seller
 * the New bill page plus today's published price list JSON
 * (/e/{token}/prices.json). Live/voice features need the network and are
 * marked "needs internet" by offline-bills.js when offline.
 */

const CACHE = "mm-shell-v3";

const SHELL = [
  "/static/app.css",
  "/static/methods.js",
  "/static/quote.js",
  "/static/tap-chips.js",
  "/static/live-order.js",
  "/static/recorder.js",
  "/static/upload.js",
  "/static/photo.js",
  "/static/pcm-worklet.js",
  "/static/live.js",
  "/static/offline-bills.js",
  "/static/fonts/InterVariable.woff2",
  "/static/fonts/InterVariable.ttf",
  "/static/fonts/NotoSansTamil-Regular.ttf",
  "/static/fonts/NotoSansTamil-Bold.ttf",
  "/static/brand/icon-192.png",
  "/static/brand/icon-512.png",
  "/static/brand/logo.svg",
  "/static/brand/mark.svg",
  "/static/icons/fluent/house.svg",
  "/static/icons/fluent/mic.svg",
  "/static/icons/fluent/bags.svg",
  "/static/icons/fluent/receipt.svg",
  "/static/icons/fluent/ledger.svg",
  "/static/icons/fluent/moon.svg",
  "/static/icons/fluent/cash.svg",
  "/static/icons/fluent/phone.svg",
  "/static/icons/fluent/chat.svg",
  "/static/icons/fluent/call.svg",
  "/static/icons/fluent/link.svg",
  "/static/icons/fluent/printer.svg",
  "/static/icons/fluent/tag.svg",
  "/static/icons/fluent/camera.svg",
  "/static/icons/fluent/video.svg",
  "/static/icons/fluent/basket.svg",
  "/static/icons/fluent/cart.svg",
  "/static/icons/fluent/store.svg",
  "/static/icons/fluent/pin.svg",
  "/static/icons/fluent/clock.svg",
  "/static/icons/fluent/check.svg",
  "/static/icons/fluent/warning.svg",
  "/static/icons/fluent/bell.svg",
  "/static/icons/fluent/customer.svg",
  "/static/icons/fluent/package.svg",
  "/static/icons/fluent/scale.svg",
  "/static/icons/fluent/tomato.svg",
  "/static/icons/fluent/carrot.svg",
  "/static/icons/fluent/greens.svg",
  "/static/icons/fluent/chart.svg",
  "/static/icons/fluent/calendar.svg",
  "/static/icons/fluent/search.svg",
  "/static/icons/fluent/settings.svg",
  "/static/icons/fluent/robot.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

function isPricesJson(url) {
  return /\/e\/[^/]+\/prices\.json$/.test(url.pathname);
}

function isNewBillPage(url) {
  return /\/e\/[^/]+\/bills\/new$/.test(url.pathname);
}

function networkFirst(request) {
  return fetch(request)
    .then((response) => {
      if (response && response.ok) {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(request, copy));
      }
      return response;
    })
    .catch(() => caches.match(request));
}

function cacheFirst(request) {
  return caches.match(request).then((hit) => hit || fetch(request));
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method === "POST" && url.origin === self.location.origin && url.pathname === "/share") {
    event.respondWith(
      (async () => {
        const cache = await caches.open("mm-share");
        try {
          const form = await request.formData();
          const file = form.get("media");
          if (file) {
            await cache.put(
              "shared-file",
              new Response(file, {
                headers: {
                  "Content-Type": file.type || "application/octet-stream",
                  "X-File-Name": encodeURIComponent(file.name || "shared"),
                },
              }),
            );
          }
        } catch (err) {
          /* fall through to the share page empty state */
        }
        return Response.redirect("/share?got=1", 303);
      })(),
    );
    return;
  }
  if (request.method !== "GET") {
    return;
  }
  if (url.origin !== self.location.origin) {
    return;
  }
  if (isPricesJson(url) || isNewBillPage(url)) {
    event.respondWith(networkFirst(request));
    return;
  }
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(cacheFirst(request));
  }
});
