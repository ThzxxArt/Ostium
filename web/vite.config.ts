import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      registerType: 'prompt',
      injectRegister: 'auto',
      includeAssets: ['icons/favicon.svg', 'icons/apple-touch-icon.png'],
      manifest: {
        name: 'Ostium',
        short_name: 'Ostium',
        description: 'A private, dual-role VPN and proxy console.',
        theme_color: '#060911',
        background_color: '#060911',
        display: 'standalone',
        start_url: '/',
        scope: '/',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/icons/maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
          { src: '/icons/favicon.svg', sizes: 'any', type: 'image/svg+xml' },
        ],
      },
      workbox: {
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/sub\//],
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith('/api/'),
            handler: 'NetworkOnly',
          },
        ],
      },
      devOptions: { enabled: false },
    }),
  ],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8443', changeOrigin: false },
      '/sub': { target: 'http://127.0.0.1:8443', changeOrigin: false },
      '/ws': { target: 'ws://127.0.0.1:8443', ws: true },
    },
  },
  build: {
    target: 'es2022',
    cssCodeSplit: true,
    sourcemap: false,
    chunkSizeWarningLimit: 700,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/unit/**/*.test.ts'],
    setupFiles: ['./tests/setup.ts'],
  },
})
