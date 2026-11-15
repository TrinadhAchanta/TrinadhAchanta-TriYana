/* Triyana service worker: makes both apps installable, shows an offline notice and shows push alerts
   (new requests for doctors, visit updates for patients). API calls always go to the network. */
const SHELL = "triyana-shell-v2";
const OFFLINE = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Offline</title>
<body style="font-family:system-ui;display:grid;place-items:center;height:100vh;margin:0;background:#062e29;color:#fff;text-align:center">
<div><h1>You're offline</h1><p>Triyana needs a connection for bookings and live tracking.</p></div>`;
self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;
  e.respondWith(fetch(e.request).catch(() => new Response(OFFLINE, { headers: { "Content-Type": "text/html" } })));
});

self.addEventListener("push", (e) => {
  let m = {};
  try { m = e.data ? e.data.json() : {}; } catch { m = { title: "Triyana", body: e.data ? e.data.text() : "" }; }
  const provider = (m.url || "/") === "/provider";
  e.waitUntil(self.registration.showNotification(m.title || "Triyana", {
    body: m.body || "",
    tag: m.tag || undefined,
    renotify: !!m.urgent,
    requireInteraction: !!m.urgent,
    vibrate: m.urgent ? [400, 150, 400, 150, 400] : [200],
    icon: provider ? "/static/icons/provider-192.png" : "/static/icons/patient-192.png",
    badge: provider ? "/static/icons/provider-192.png" : "/static/icons/patient-192.png",
    data: { url: m.url || "/", link: m.link || "" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const open = wins.find((w) => new URL(w.url).pathname === url);
    if (open) return open.focus();
    return self.clients.openWindow(url);
  })());
});
