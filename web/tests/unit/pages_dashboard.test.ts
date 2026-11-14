import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DashboardPage from '@/pages/DashboardPage.vue'
import { cleanupPage, fixtures, installFetchMock, mountPage, settle } from './helpers'

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

  it('does not count skipped inbounds, offline users or pending certificates as ready', async () => {
    installFetchMock({
      overrides: {
        '/api/v1/stats/overview': {
          ...fixtures.stats,
          online_users: [
            ...fixtures.stats.online_users,
            { id: 'user-2', name: 'bob', up: 0, down: 0, online: false },
          ],
        },
        '/api/v1/inbounds': {
          inbounds: [
            { ...fixtures.inbounds[0], active: false },
            { ...fixtures.inbounds[1], enabled: true, active: true },
          ],
        },
        '/api/v1/certificates': {
          certificates: [
            { ...fixtures.certificate, status: 'pending', days_remaining: null, expires_at: null },
          ],
        },
      },
    })
    const { wrapper } = await mountPage(DashboardPage)
    await settle()
    const state = (wrapper.findComponent(DashboardPage).vm as any).$.setupState
    expect(state.activeInbounds).toBe(1)
    expect(wrapper.text()).not.toContain('bob')
    expect(wrapper.text()).toContain('Pending')
  })
})
