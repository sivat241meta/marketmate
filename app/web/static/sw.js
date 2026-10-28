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
