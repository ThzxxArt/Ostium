import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DashboardPage from '@/pages/DashboardPage.vue'
import { cleanupPage, installFetchMock, mountPage, settle } from './helpers'

describe('DashboardPage', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
    installFetchMock()
  })
  afterEach(() => {
    cleanupPage()
    vi.unstubAllGlobals()
  })

  it('renders live server data', async () => {
    const { wrapper } = await mountPage(DashboardPage)
    await settle()
    expect(wrapper.text()).toContain('Overview')
    expect(wrapper.text()).toContain('alice')
    expect(document.body.innerHTML.length).toBeGreaterThan(100)
  })
})
