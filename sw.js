const CACHE_NAME = 'monitor-turnos-v2';

// Archivos estáticos: cache-first
const CACHE_STATIC = [
    '/',
    '/index.html',
    'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js'
];

// Archivos de datos: network-first con fallback a cache
const DATA_FILES = [
    'estado_turnos.json',
    'estadisticas_db.json',
    'heartbeat.json'
];

// Instalar: cachear archivos estáticos
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(CACHE_STATIC))
    );
    self.skipWaiting();
});

// Activar: limpiar caches viejos
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// Fetch: estrategia según tipo de archivo
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);
    const isDataFile = DATA_FILES.some(f => url.pathname.endsWith(f));

    if (isDataFile) {
        // Network-first: intenta red, si falla usa cache
        event.respondWith(
            fetch(event.request)
                .then(response => {
                    if (response.ok) {
                        const clone = response.clone();
                        caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                    }
                    return response;
                })
                .catch(() => caches.match(event.request))
        );
    } else {
        // Cache-first: usa cache si existe, sino red
        event.respondWith(
            caches.match(event.request).then(cached => {
                if (cached) return cached;
                return fetch(event.request).then(response => {
                    if (response.ok) {
                        const clone = response.clone();
                        caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                    }
                    return response;
                });
            })
        );
    }
});
