// Never cache authenticated pages, API responses, images or bookings.
const CACHE = 'bokning-shell-v1';
const SHELL = ['/bokning/offline/', '/bokning/static/bokning/app.css', '/bokning/static/bokning/app.js', '/bokning/static/bokning/icon-192.png', '/bokning/static/bokning/icon-512.png'];
self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    for (const url of SHELL) {
      const response = await fetch(url, { credentials: 'omit' });
      if (!response.ok) throw new Error('Offline shell unavailable');
      await cache.put(url, response);
    }
    await self.skipWaiting();
  })());
});
self.addEventListener('activate', event => event.waitUntil((async () => {
  for (const key of await caches.keys()) if (key.startsWith('bokning-shell-') && key !== CACHE) await caches.delete(key);
  await self.clients.claim();
})()));
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || !url.pathname.startsWith('/bokning/')) return;
  if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request).catch(async () => (await caches.match('/bokning/offline/')) || Response.error()));
  } else if (SHELL.includes(url.pathname)) {
    event.respondWith(fetch(event.request).catch(() => caches.match(url.pathname)));
  }
});
