// Numele cache-ului - increment la schimbări ca să forțezi refresh la useri
const CACHE_NAME = 's366-ai-v3';

const ORIGIN = self.location.origin;
const ASSETS_TO_CACHE = [
  `${ORIGIN}/chat`,
  `${ORIGIN}/static/images/icons/icon-192x192.png`,
  `${ORIGIN}/static/images/og/chat-ai-s366.png`,
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS_TO_CACHE))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) =>
      Promise.all(cacheNames.map((cache) => (cache !== CACHE_NAME ? caches.delete(cache) : null)))
    )
  );
});

self.addEventListener('fetch', (event) => {
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});

self.addEventListener('push', (event) => {
  if (event.data) {
    const message = event.data.json();
    event.waitUntil(
      self.registration.showNotification(message.title, {
        body: message.body,
        icon: message.icon || '/static/images/icons/icon-192x192.png',
        badge: '/static/images/icons/icon-192x192.png'
      })
    );
  }
});
