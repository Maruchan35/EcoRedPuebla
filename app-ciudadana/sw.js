const CACHE_NAME = "ecored-puebla-v7";
const STATIC_ASSETS = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icons/icon.svg",
  "./css/styles.css",
  "./js/config.js",
  "./js/exif.js",
  "./js/vision-local.js",
  "./js/offline-queue.js",
  "./js/api.js",
  "./js/camera-gps.js",
  "./js/app.js",
  "./vendor/lucide.min.js",
  "./vendor/leaflet/leaflet.css",
  "./vendor/leaflet/leaflet.js",
  "./vendor/leaflet/images/marker-icon.png",
  "./vendor/leaflet/images/marker-icon-2x.png",
  "./vendor/leaflet/images/marker-shadow.png",
  "./vendor/fonts/lexend-latin-400-normal.woff2",
  "./vendor/fonts/lexend-latin-500-normal.woff2",
  "./vendor/fonts/lexend-latin-600-normal.woff2",
  "./vendor/fonts/source-sans-3-latin-400-normal.woff2",
  "./vendor/fonts/source-sans-3-latin-600-normal.woff2",
  "./vendor/fonts/source-sans-3-latin-700-normal.woff2"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // Never intercept API calls, WebSockets or external map tiles
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")) {
    return;
  }

  // Vendor fonts/libs: cache-first
  if (url.pathname.includes("/vendor/") || url.pathname.includes("/icons/")) {
    event.respondWith(
      caches.match(req).then((cached) => cached || fetch(req).then((res) => {
        if (res && res.ok) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
        }
        return res;
      }))
    );
    return;
  }

  // App shell (HTML, CSS, JS): network-first with cache fallback for offline mode
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.ok) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
        }
        return res;
      })
      .catch(() => caches.match(req).then((cached) => cached || caches.match("./index.html")))
  );
});
