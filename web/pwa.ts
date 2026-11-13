import { createHash } from 'node:crypto'
import { readdir, readFile, writeFile } from 'node:fs/promises'
import { join, relative, sep } from 'node:path'
import type { Plugin } from 'vite'

const PRECACHE_RE = /\.(?:js|css|html|svg|png|woff2|webmanifest|json)$/

async function walk(directory: string, base = directory): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true })
  const files: string[] = []
  for (const entry of entries) {
    const full = join(directory, entry.name)
    if (entry.isDirectory()) {
      files.push(...(await walk(full, base)))
    } else if (entry.isFile()) {
      files.push(relative(base, full))
    }
  }
  return files
}

function workerSource(assets: string[], digest: string): string {
  return `const CACHE = 'ostium-${digest}';
const ASSETS = ${JSON.stringify(assets)};

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/sub/')) return;

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            void caches.open(CACHE).then((cache) => cache.put('/index.html', copy));
          }
          return response;
        })
        .catch(() => caches.match('/index.html').then((cached) => cached || Response.error()))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          void caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      });
    })
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});
`
}

export interface GeneratedServiceWorker {
  source: string
  files: string[]
  digest: string
}

/**
 * Build a deterministic precache service worker for ``outDir``.
 *
 * The cache key hashes both the asset names and their contents.  Hashing only
 * names would leave stable-name assets (``index.html``, the manifest and
 * ``theme-init.js``) permanently stale whenever their contents changed.
 */
export async function buildServiceWorker(outDir: string): Promise<GeneratedServiceWorker> {
  const files = (await walk(outDir))
    .filter((file) => file !== 'sw.js' && PRECACHE_RE.test(file))
    .map((file) => file.split(sep).join('/'))
    .sort()
  const hashes = await Promise.all(
    files.map(async (file) => {
      const content = await readFile(join(outDir, ...file.split('/')))
      return `${file}:${createHash('sha256').update(content).digest('hex')}`
    }),
  )
  const digest = createHash('sha256').update(hashes.join('\n')).digest('hex').slice(0, 12)
  return {
    source: workerSource(
      files.map((file) => `/${file}`),
      digest,
    ),
    files,
    digest,
  }
}

/**
 * Small replacement for vite-plugin-pwa/workbox.  It emits a deterministic
 * precache service worker after Vite has written the bundle; no third-party
 * runtime or build dependency is involved.
 */
export function ostiumPwa(): Plugin {
  let outDir = 'dist'
  return {
    name: 'ostium-pwa',
    apply: 'build',
    configResolved(config) {
      outDir = config.build.outDir
    },
    async closeBundle() {
      const generated = await buildServiceWorker(outDir)
      await writeFile(join(outDir, 'sw.js'), generated.source)
      // Keep the emitted file in the build log without depending on a plugin.
      this.info(
        `generated sw.js (${generated.source.length} bytes, ${generated.files.length} precached files)`,
      )
    },
  }
}
