/* Service worker — Pluvio RWH
   Deux caches separes evitent de retelecharger les 13 Mo de donnees a chaque
   evolution de l'interface. Incrementer APP_CACHE pour le code, DATA_CACHE
   uniquement lors d'une regeneration de normales_france.json. */
const APP_CACHE = "pluvio-rwh-v29";
const DATA_CACHE = "pluvio-rwh-data-v1";
const APP_ASSETS = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./icon-192.png",
  "./icon-512.png",
  "./vendor/leaflet/leaflet.js",
  "./vendor/leaflet/leaflet.css"
];

// Installation : pre-cache de tout le necessaire
self.addEventListener("install", (e) => {
  e.waitUntil(
    Promise.all([
      caches.open(APP_CACHE).then((c) => c.addAll(APP_ASSETS)),
      caches.open(DATA_CACHE).then((c) =>
        c.match("./normales_france.json").then((cached) =>
          cached || c.add("./normales_france.json")
        )
      )
    ]).then(() => self.skipWaiting())
  );
});

// Activation : suppression des anciens caches
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== APP_CACHE && k !== DATA_CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Le gros JSON, versionne par DATA_CACHE, est servi depuis le cache. Le reste
// reste reseau d'abord pour diffuser rapidement les corrections d'interface.
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin === self.location.origin && url.pathname.endsWith("/normales_france.json")) {
    e.respondWith(
      caches.open(DATA_CACHE).then((c) =>
        c.match(req).then((cached) => cached || fetch(req).then((resp) => {
          if (!resp.ok) return resp;
          // Une erreur de quota cache ne doit pas masquer une reponse reseau valide.
          return c.put(req, resp.clone()).then(() => resp, () => resp);
        }).catch(() =>
          // Le cache peut avoir ete rempli entre le premier match et l'echec reseau.
          c.match(req).then((fallback) => fallback || Response.error())
        ))
      )
    );
    return;
  }
  e.respondWith(
    fetch(req)
      .then((resp) => {
        if (resp.ok && new URL(req.url).origin === self.location.origin) {
          const copy = resp.clone();
          caches.open(APP_CACHE).then((c) => c.put(req, copy));
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
