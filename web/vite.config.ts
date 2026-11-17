import { fileURLToPath, URL } from 'node:url'
import { readFileSync } from 'node:fs'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'
import { ostiumPwa } from './pwa.ts'

const VERSION = readFileSync(new URL('../VERSION', import.meta.url), 'utf8').trim()
const COMMIT = process.env.OSTIUM_BUILD_COMMIT ?? process.env.GITHUB_SHA ?? ''
const BUILT_AT = process.env.OSTIUM_BUILD_TIME ?? new Date().toISOString()

export default defineConfig({
  plugins: [vue(), ostiumPwa({ version: VERSION, commit: COMMIT, builtAt: BUILT_AT })],
  define: {
    __APP_VERSION__: JSON.stringify(VERSION),
    __BUILD_COMMIT__: JSON.stringify(COMMIT),
    __BUILD_TIME__: JSON.stringify(BUILT_AT),
  },
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
    testTimeout: 60_000,
    hookTimeout: 60_000,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,vue}'],
      exclude: ['src/env.d.ts', 'src/api/types.ts'],
      thresholds: {
        statements: 85,
        branches: 85,
        functions: 85,
        lines: 85,
      },
    },
  },
})
