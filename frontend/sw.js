/* Triyana service worker: makes both apps installable and shows an offline notice. API calls always go to the network. */
const SHELL = "triyana-shell-v1";
const OFFLINE = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Offline</title>
<body style="font-family:system-ui;display:grid;place-items:center;height:100vh;margin:0;background:#062e29;color:#fff;text-align:center">
<div><h1>You're offline</h1><p>Triyana needs a connection for bookings and live tracking.</p></div>`;
self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;
  e.respondWith(fetch(e.request).catch(() => new Response(OFFLINE, { headers: { "Content-Type": "text/html" } })));
});
