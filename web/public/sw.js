// Development placeholder. The production build overwrites this file with the
// generated precache service worker via web/build/pwa.ts.
self.addEventListener('install', () => {
  self.skipWaiting()
})
self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})
