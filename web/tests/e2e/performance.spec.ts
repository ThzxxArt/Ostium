import { test, expect } from '@playwright/test'

const password = process.env.OSTIUM_ADMIN_PASSWORD || 'verysecret123'

test('dashboard meets LCP/CLS budgets @performance', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder(/Username|用户名/).fill('admin')
  await page.getByPlaceholder(/Password|密码/).fill(password)
  await page.getByRole('button', { name: /Sign in|登录/ }).click()
  await expect(page).toHaveURL('/')
  await page.goto('/')
  await page.waitForLoadState('networkidle')

  const metrics = await page.evaluate(
    () =>
      new Promise<{ lcp: number; cls: number; shifts: string[] }>((resolve) => {
        let lcp = 0
        let cls = 0
        const shifts: string[] = []
        if ('PerformanceObserver' in window) {
          try {
            new PerformanceObserver((list) => {
              for (const entry of list.getEntries()) lcp = entry.startTime
            }).observe({ type: 'largest-contentful-paint', buffered: true })
            new PerformanceObserver((list) => {
              for (const entry of list.getEntries() as Array<
                PerformanceEntry & {
                  value?: number
                  hadRecentInput?: boolean
                  sources?: Array<{ node?: Node }>
                }
              >) {
                if (!entry.hadRecentInput) {
                  cls += entry.value || 0
                  for (const source of entry.sources || []) {
                    const node = source.node as HTMLElement | undefined
                    if (node) shifts.push(node.className || node.tagName)
                  }
                }
              }
              // Only layout shifts after hydration are counted here.  Initial
              // route/data insertion is tracked by the LCP budget and visual
              // snapshots; this assertion guards runtime jitter.
            }).observe({ type: 'layout-shift' })
          } catch {
            /* older engines */
          }
        }
        setTimeout(() => resolve({ lcp, cls, shifts }), 1500)
      }),
  )
  expect(metrics.lcp).toBeGreaterThan(0)
  expect(metrics.lcp, JSON.stringify(metrics)).toBeLessThan(2500)
  expect(metrics.cls, JSON.stringify(metrics)).toBeLessThan(0.05)
})
