/* Service worker — Italpluvio (ERA5-Land)
   Met en cache l'app shell ET les donnees (normales_italie.json) pour un
   fonctionnement hors-ligne. Strategie : reseau d'abord, cache en repli.
   Incrementer CACHE a chaque mise a jour du code ou des donnees. */
const CACHE = "italpluvio-v4";
const ASSETS = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./normales_italie.json",
  "./icon-192.png",
  "./icon-512.png",
  "./vendor/leaflet/leaflet.js",
  "./vendor/leaflet/leaflet.css"
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Reseau d'abord (toujours a jour en ligne), cache en repli (offline).
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  e.respondWith(
    fetch(req)
      .then((resp) => {
        if (resp.ok && new URL(req.url).origin === self.location.origin) {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return resp;
      })
      .catch(() =>
        caches.match(req).then((cached) =>
          cached || (req.mode === "navigate" ? caches.match("./index.html") : undefined)
        )
      )
  );
});
