const CACHE_NAME = 'monitor-turnos-v4';

// Archivos estáticos: cache-first
const CACHE_STATIC = [
    '/',
    '/index.html',
    'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js'
];

// Archivos de datos (Railway): stale-while-revalidate
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
    const isDataFile = url.hostname.endsWith('railway.app') || DATA_FILES.some(f => url.pathname.endsWith(f));

    if (isDataFile) {
        // Stale-while-revalidate: responde al instante con la copia en cache si existe,
        // y en paralelo pide la versión fresca a la red y actualiza la cache para el próximo refresco.
        // Si no hay cache, espera la red (como antes).
        event.respondWith(
            caches.match(event.request).then(cached => {
                const fresca = fetch(event.request)
                    .then(response => {
                        if (response.ok) {
                            const clone = response.clone();
                            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                        }
                        return response;
                    })
                    .catch(() => cached);
                return cached || fresca;
            })
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
