/* Service worker — Pluvio RWH
   Met en cache l'app shell ET les donnees (normales_france.json) pour un
   fonctionnement 100% hors-ligne. Strategie : cache-first.
   Incrementer CACHE a chaque mise a jour du code ou des donnees. */
const CACHE = "pluvio-rwh-v6";
const ASSETS = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./normales_france.json",
  "./icon-192.png",
  "./icon-512.png",
  "./vendor/leaflet/leaflet.js",
  "./vendor/leaflet/leaflet.css"
];

// Installation : pre-cache de tout le necessaire
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

// Activation : suppression des anciens caches
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Requetes : RESEAU d'abord (toujours a jour en ligne), cache en repli (offline).
// On met le cache a jour a chaque reponse reseau valide.
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
