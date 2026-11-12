import { test, expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const password = process.env.OSTIUM_ADMIN_PASSWORD || 'verysecret123'

const visualStats = {
  role: 'server',
  users: { total: 3, enabled: 2, online: 1, disabled: 1 },
  traffic: {
    today_up: 512 * 1024 * 1024,
    today_down: 1024 * 1024 * 1024,
    session_up: 128 * 1024 * 1024,
    session_down: 256 * 1024 * 1024,
  },
  rates: { up: 128 * 1024, down: 256 * 1024 },
  engine: {
    running: true,
    revision: 'visual-baseline',
    engine_version: '1.14.4-ostium.1',
    last_error: null,
    started_at: '2026-11-01T10:00:00Z',
  },
  connections: 12,
  online_users: [{ id: 'user-1', name: 'alice', up: 64 * 1024, down: 128 * 1024, online: true }],
  generated_at: '2026-11-12T10:00:00Z',
}

const visualTraffic = {
  series: [
    { day: '2026-11-06', up: 120_000_000, down: 340_000_000 },
    { day: '2026-11-07', up: 160_000_000, down: 420_000_000 },
    { day: '2026-11-08', up: 90_000_000, down: 260_000_000 },
    { day: '2026-11-09', up: 210_000_000, down: 510_000_000 },
    { day: '2026-11-10', up: 180_000_000, down: 470_000_000 },
    { day: '2026-11-11', up: 140_000_000, down: 390_000_000 },
    { day: '2026-11-12', up: 110_000_000, down: 320_000_000 },
  ],
  days: 7,
  user_id: null,
}

const visualInbounds = [
  {
    id: 'in-1',
    kind: 'vless',
    enabled: true,
    listen: '0.0.0.0',
    port: 443,
    default_port: 443,
    params: { has_obfs: false, has_server_key: true },
    certificate: null,
    requires_certificate: false,
    updated_at: '2026-11-01T10:00:00Z',
  },
  {
    id: 'in-2',
    kind: 'shadowsocks',
    enabled: false,
    listen: '0.0.0.0',
    port: 8388,
    default_port: 8388,
    params: { has_obfs: false, has_server_key: false },
    certificate: null,
    requires_certificate: false,
    updated_at: '2026-11-01T10:00:00Z',
  },
]

const visualCertificates = [
  {
    id: 'cert-1',
    domain: 'vpn.example.com',
    issuer: "Let's Encrypt",
    expires_at: '2027-01-23T10:00:00Z',
    auto_renew: true,
    status: 'ready',
    source: 'acme',
    last_error: null,
    created_at: '2026-10-24T10:00:00Z',
    days_remaining: 72,
  },
]

const visualInfo = {
  app: { name: 'Ostium', version: '0.1.0', role: 'server' },
  host: {
    hostname: 'vpn',
    platform: 'Linux-6.8.0',
    system: 'Linux',
    machine: 'x86_64',
    python: '3.13.5',
    uptime_seconds: 345_600,
    pid: 1234,
  },
  metrics: {
    cpu_percent: 12,
    load_1m: 0.42,
    memory_percent: 40,
    memory_used: 1024 * 1024 * 1024,
    memory_total: 4 * 1024 * 1024 * 1024,
    disk_percent: 55,
    disk_used: 20 * 1024 * 1024 * 1024,
    disk_total: 40 * 1024 * 1024 * 1024,
  },
  core: { running: true, pid: 1234 },
  control_plane_uptime: 86_400,
  server_host: 'vpn.example.com',
  mode: 'mixed',
  proxy: {
    supported: true,
    platform: 'linux-gnome',
    enabled: false,
    host: '127.0.0.1',
    port: 7890,
  },
  tun: { enabled: false, interface: 'ostium0', mtu: 1500, stack: 'gvisor' },
}

async function mockVisualDashboard(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.startsWith('/api/v1/auth/')) {
      await route.continue()
      return
    }
    const payloads: Record<string, unknown> = {
      '/api/v1/stats/overview': visualStats,
      '/api/v1/stats/traffic': visualTraffic,
      '/api/v1/alerts': { alerts: [] },
      '/api/v1/inbounds': { inbounds: visualInbounds },
      '/api/v1/certificates': { certificates: visualCertificates },
      '/api/v1/system/info': visualInfo,
    }
    const payload = payloads[path]
    if (payload === undefined) {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    })
  })
  await page.routeWebSocket(/\/api\/v1\/events$/, () => {
    // Hold the socket open without sending frames so no time-based event text
    // can leak into the screenshot.
  })
}

async function login(page: Page) {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: /Welcome back|欢迎回来/ })).toBeVisible()
  await page.getByPlaceholder(/Username|用户名/).fill('admin')
  await page.getByPlaceholder(/Password|密码/).fill(password)
  await page.getByRole('button', { name: /Sign in|登录/ }).click()
  await expect(page).toHaveURL('/')
}

test('login and dashboard are usable', async ({ page }) => {
  await login(page)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.getByText(/Server pulse|服务脉搏/)).toBeVisible()
})

test('command palette opens and navigates', async ({ page }) => {
  await login(page)
  await page.keyboard.press('Control+k')
  const input = page.getByPlaceholder(/Search pages|搜索页面/)
  await expect(input).toBeVisible()
  await input.fill('users')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/users/)
})

test('login page has no serious accessibility violations', async ({ page }) => {
  await page.goto('/login')
  const results = await new AxeBuilder({ page }).disableRules(['color-contrast']).analyze()
  const serious = results.violations.filter((item) =>
    ['serious', 'critical'].includes(item.impact || ''),
  )
  expect(serious).toEqual([])
})

test('responsive layout has no horizontal scroll', async ({ page }) => {
  await login(page)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  )
  expect(overflow).toBeLessThanOrEqual(2)
})

for (const theme of ['dark', 'light'] as const) {
  test(`visual dashboard ${theme} @visual`, async ({ page }) => {
    await page.clock.install({ time: new Date('2026-11-12T10:00:00Z') })
    await page.addInitScript((value) => {
      localStorage.setItem('ostium.theme', value)
    }, theme)
    await mockVisualDashboard(page)
    await login(page)
    await expect(page.getByText(/Server pulse|服务脉搏/)).toBeVisible()
    await expect(
      page
        .getByText(/Proxy core is running|代理核心运行中/)
        .filter({ visible: true })
        .first(),
    ).toBeVisible()
    await expect(page.getByText(/1 Active inbounds|1 可用线路/).first()).toBeVisible()
    await page.locator('.lazy-chart').first().scrollIntoViewIfNeeded()
    await expect(page.locator('canvas').first()).toBeVisible()
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.addStyleTag({ content: '.mobile-nav { display: none !important; }' })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot(`dashboard-${theme}.png`, {
      fullPage: true,
      animations: 'disabled',
      caret: 'hide',
      maxDiffPixelRatio: 0.01,
    })
  })
}
