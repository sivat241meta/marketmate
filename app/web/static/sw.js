/* MarketMate service worker: offline tap-billing shell.
 *
 * Caches the app shell (CSS, JS, fonts, icons) on install, and per seller
 * the New bill page plus today's published price list JSON
 * (/e/{token}/prices.json). Live/voice features need the network and are
 * marked "needs internet" by offline-bills.js when offline.
 */

const CACHE = "mm-shell-v1";

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
  "/static/fonts/NotoSansTamil-Regular.ttf",
  "/static/fonts/NotoSansTamil-Bold.ttf",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
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
  if (request.method !== "GET") {
    return;
  }
  const url = new URL(request.url);
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
