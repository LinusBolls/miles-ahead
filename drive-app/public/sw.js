// Offline support for the Rescue concept PWA. Network-first for everything (so a redeploy shows up immediately),
// falling back to the cache when offline. Map tiles are cached as they're viewed, so a once-loaded area works offline.
const CACHE = "rescue-concept-v2";
const SHELL = ["/app/", "/app/api/vehicles.json", "/app/vendor/maplibre-gl.js", "/app/vendor/maplibre-gl.css", "/app/manifest.json"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const ours = url.origin === self.location.origin && url.pathname.startsWith("/app/");
  const tiles = /openfreemap\.org|basemaps\.cartocdn\.com/.test(url.hostname);
  if (!ours && !tiles) return;
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res && (res.ok || res.type === "opaque")) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      })
      .catch(() =>
        caches.match(req).then((hit) => hit || (req.mode === "navigate" ? caches.match("/app/") : Response.error())),
      ),
  );
});
