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
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put('/index.html', copy));
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
          caches.open(CACHE).then((cache) => cache.put(request, copy));
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

/**
 * Small replacement for vite-plugin-pwa/workbox.  It emits a deterministic
 * precache service worker after Vite has written the bundle; no third-party
 * runtime or build dependency is involved.
 */export function ostiumPwa(): Plugin {
  let outDir = 'dist'
  return {
    name: 'ostium-pwa',
    apply: 'build',
    configResolved(config) {
      outDir = config.build.outDir
    },
    async closeBundle() {
      const files = (await walk(outDir))
        .filter((file) => file !== 'sw.js' && PRECACHE_RE.test(file))
        .map((file) => `/${file.split(sep).join('/')}`)
        .sort()
      const digest = createHash('sha256').update(files.join('\n')).digest('hex').slice(0, 12)
      await writeFile(join(outDir, 'sw.js'), workerSource(files, digest))
      // Keep the emitted file in the build log without depending on a plugin.
      const sw = await readFile(join(outDir, 'sw.js'), 'utf8')
      this.info(`generated sw.js (${sw.length} bytes, ${files.length} precached files)`)
    },
  }
}
