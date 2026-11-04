/* Cache only shipped application files. Memories stay in IndexedDB, never HTTP. */
const CACHE_PREFIX = 'love-house-mobile-static-';
const CACHE = CACHE_PREFIX + '0.8.0rc2-r1';
const FILES = [
  './', './index.html', './styles.css', './app.js', './store.js', './service-link.js', './register-sw.js',
  './manifest.webmanifest', './assets/love-house-icon.png', './assets/ark-pixel.woff2',
  './assets/ark-pixel-OFL.txt'
];
const allowed = new Set(FILES.map(path => new URL(path, self.registration.scope).href));
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(names => Promise.all(names
    .filter(name => name.startsWith(CACHE_PREFIX) && name !== CACHE)
    .map(name => caches.delete(name)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin || !allowed.has(url.href)) return;
  event.respondWith(caches.open(CACHE).then(async cache => {
    const saved = await cache.match(request);
    if (saved) return saved;
    const response = await fetch(request);
    if (response.ok && response.type === 'basic') await cache.put(request, response.clone());
    return response;
  }));
});
