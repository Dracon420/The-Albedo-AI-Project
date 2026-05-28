// Albedo PWA — Service Worker
// Minimal SW: enables installability + offline fallback

const CACHE = 'albedo-v1';
const PRECACHE = ['/', '/app/', '/app/index.html', '/app/app.js', '/app/manifest.json', '/app/icon-192.png', '/app/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(PRECACHE).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  // Network-first for WebSocket and API calls, cache-first for static
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/ws') || url.pathname.startsWith('/pair') || url.pathname.startsWith('/status')) {
    return; // Don't intercept WS/API
  }
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});

// Push notifications
self.addEventListener('push', e => {
  const data = e.data ? e.data.json() : { title: 'Albedo', body: 'New message' };
  e.waitUntil(
    self.registration.showNotification(data.title || 'Albedo', {
      body: data.body || '',
      icon: '/app/icon-192.png',
      badge: '/app/icon-192.png',
    })
  );
});
