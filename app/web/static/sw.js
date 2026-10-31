/* MarketMate service worker (Task 150).
 *
 * Caches the static app shell (CSS, JS, fonts, icons) on install for
 * fast repeat loads. Seller pages and API JSON are never cached:
 * every non-static request goes to the network, and a navigation
 * that fails (the phone is offline) falls back to a small inline
 * offline page. Queued offline bills still sync from localStorage
 * through offline-bills.js once the phone is back online.
 */

const CACHE = "mm-shell-v4";

const SHELL = [
  "/static/app.css",
  "/static/css/composer.css",
  "/static/css/forms.css",
  "/static/css/home.css",
  "/static/css/motion.css",
  "/static/css/public.css",
  "/static/css/seller.css",
  "/static/css/shop13.css",
  "/static/css/v13.css",
  "/static/ai.js",
  "/static/cash.js",
  "/static/composer.js",
  "/static/customer-contact.js",
  "/static/home.js",
  "/static/live.js",
  "/static/locate.js",
  "/static/methods.js",
  "/static/motion.js",
  "/static/my.js",
  "/static/near-me.js",
  "/static/offline-bills.js",
  "/static/order-alert.js",
  "/static/order-status.js",
  "/static/pcm-worklet.js",
  "/static/photo.js",
  "/static/pnav.js",
  "/static/popups.js",
  "/static/public.js",
  "/static/quote.js",
  "/static/rename-dialog.js",
  "/static/review.js",
  "/static/tap-chips.js",
  "/static/upload.js",
  "/static/fonts/PlusJakartaSans-Variable.ttf",
  "/static/fonts/InterVariable.woff2",
  "/static/fonts/InterVariable.ttf",
  "/static/fonts/NotoSansTamil-Regular.ttf",
  "/static/fonts/NotoSansTamil-Bold.ttf",
  "/static/fonts/NotoSansDevanagari-Regular.ttf",
  "/static/fonts/NotoSansDevanagari-Bold.ttf",
  "/static/brand/icon-192.png",
  "/static/brand/icon-512.png",
  "/static/brand/icon-maskable-512.png",
  "/static/brand/apple-touch-icon.png",
  "/static/brand/logo.svg",
  "/static/brand/mark.svg",
  "/static/brand/mark-dark.svg",
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

const OFFLINE_HTML = "<!doctype html><html lang=\"en\"><head>"
  + "<meta charset=\"utf-8\">"
  + "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
  + "<title>MarketMate — offline</title>"
  + "<style>body{font-family:system-ui,sans-serif;background:#F3F8FA;"
  + "color:#102A33;margin:0;display:grid;place-items:center;"
  + "min-height:100vh;text-align:center;padding:24px}"
  + "h1{font-size:22px}a{color:#0F766E;font-weight:700}</style>"
  + "</head><body><main><h1>You are offline</h1>"
  + "<p>MarketMate needs the internet for fresh prices.</p>"
  + "<p><a href=\"/\">Try again</a></p></main></body></html>";

function offlineResponse() {
  return new Response(OFFLINE_HTML, {
    headers: { "Content-Type": "text/html" },
  });
}

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
            return Response.redirect("/share?got=1", 303);
          }
          // Task 152: shared text or a link opens it as a market search.
          const text = form.get("text") || form.get("url") || form.get("title");
          if (text) {
            return Response.redirect(
              "/market?q=" + encodeURIComponent(text), 303);
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
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(cacheFirst(request));
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => offlineResponse()));
  }
});
