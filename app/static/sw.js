// Numele cache-ului - schimbă v1 în v2 când modifici designul ca să forțezi refresh la useri
const CACHE_NAME = 's366-turbo-v1';

const ASSETS_TO_CACHE = [
  '/chat',
  '/static/images/icons/icon-192x192.png',
  '/static/images/og/chat-ai-s366.png',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css'
];

// 1. INSTALARE - Punem în cache resursele de bază
self.addEventListener('install', (event) => {
  console.log("S366: SW Instalat");
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
  self.skipWaiting(); // Forțează activarea imediată
});

// 2. ACTIVARE - Curățăm cache-ul vechi
self.addEventListener('activate', (event) => {
  console.log("S366: SW Activat");
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cache) => {
          if (cache !== CACHE_NAME) {
            return caches.delete(cache);
          }
        })
      );
    })
  );
});

// 3. FETCH - Strategie "Network First, fallback to Cache"
// Ideală pentru chat: cere date noi, dacă n-ai net, dă-le pe alea vechi
self.addEventListener('fetch', (event) => {
  event.respondWith(
    fetch(event.request).catch(() => {
      return caches.match(event.request);
    })
  );
});

// 4. PUSH NOTIFICATIONS (Păstrat din varianta ta, e bun!)
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
