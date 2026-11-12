import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.OSTIUM_BASE_URL || 'http://127.0.0.1:18443'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['html', { open: 'never' }], ['list']] : 'list',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'tablet',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1024, height: 768 } },
    },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: process.env.OSTIUM_BASE_URL
    ? undefined
    : {
        command: 'npm run dev -- --port 5173',
        url: 'http://127.0.0.1:5173',
        reuseExistingServer: true,
        timeout: 60_000,
      },
})
