// Service worker: cachea todo en la instalación → el juego anda 100% offline.
// Al tocar cualquier archivo hay que subir VER, si no el celu sirve la copia vieja.
const VER = "acu-v3";
const ASSETS = [
  "./",
  "./index.html",
  "./style.css",
  "./app.js",
  "./gen.js",
  "./banco/index.js",
  "./banco/numericos.js",
  "./banco/geometria.js",
  "./banco/fuentes.js",
  "./banco/psicoacustica.js",
  "./banco/numerica.js",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VER).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== VER).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Cache-first: es contenido estático, la velocidad importa más que la frescura.
// El VER nuevo trae la actualización.
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request).catch(() => caches.match("./index.html")))
  );
});
