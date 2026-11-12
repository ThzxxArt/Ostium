import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const password = process.env.OSTIUM_ADMIN_PASSWORD || 'verysecret123'

async function login(page: import('@playwright/test').Page) {
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

test('visual baseline @visual', async ({ page }) => {
  test.skip(!process.env.OSTIUM_VISUAL, 'set OSTIUM_VISUAL=1 to write visual baselines')
  await login(page)
  await expect(page).toHaveScreenshot('dashboard.png', { fullPage: true, maxDiffPixelRatio: 0.02 })
})
