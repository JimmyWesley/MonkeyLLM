// MonkeyLLM Studio — Service Worker (PWA install requirement)
//
// Strategy: network-first for everything. This SW exists primarily to
// satisfy the browser's installability check. It caches the app shell
// so the Studio loads instantly on repeat visits, but always tries the
// network first so deploys are never stale.

const CACHE = 'monkeyllm-studio-v1'

// App shell assets cached on install
const SHELL = [
  '/',
  '/logo.png',
  '/favicon.ico',
  '/manifest.json',
]

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (e) => {
  // Purge old caches when a new SW version activates
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (e) => {
  const { request } = e

  // Skip non-GET and API/MCP calls — those must never be cached
  if (request.method !== 'GET' ||
      request.url.includes('/v1/') ||
      request.url.includes('/mcp')) {
    return
  }

  // Network-first: try the network, fall back to cache
  e.respondWith(
    fetch(request)
      .then((response) => {
        // Cache successful responses for offline fallback
        if (response.ok) {
          const clone = response.clone()
          caches.open(CACHE).then((cache) => cache.put(request, clone))
        }
        return response
      })
      .catch(() => caches.match(request))
  )
})
