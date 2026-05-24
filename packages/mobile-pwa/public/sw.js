/* 深求 service worker — minimal v1.
 * cache-first for app shell (/src/*, /public/*, /), network-first for /v1/*.
 * Bump CACHE_NAME on any shell change to force update.
 */
const CACHE_NAME = 'dsh-shell-v1';
const SHELL = [
  '/',
  '/index.html',
  '/manifest.json',
  '../src/app.js',
  '../src/api.js',
  '../src/util.js',
  '../src/ui-login.js',
  '../src/ui-chat.js',
  '../src/ui-sessions.js',
  '../src/styles.css',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((c) => c.addAll(SHELL).catch(() => null)),
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))),
    ),
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Never intercept SSE / API traffic.
  if (url.pathname.startsWith('/v1/')) {
    event.respondWith(
      fetch(req).catch(() =>
        new Response(JSON.stringify({ error: { code: 'offline', message: '离线' } }), {
          status: 503,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    );
    return;
  }

  const isShell =
    url.pathname === '/' ||
    url.pathname.endsWith('.html') ||
    url.pathname.includes('/src/') ||
    url.pathname.includes('/public/') ||
    url.pathname.endsWith('.css') ||
    url.pathname.endsWith('.js') ||
    url.pathname.endsWith('.json') ||
    url.pathname.endsWith('.png') ||
    url.pathname.endsWith('.svg');

  if (!isShell) return;

  event.respondWith(
    caches.match(req).then(
      (hit) =>
        hit ||
        fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        }),
    ),
  );
});
