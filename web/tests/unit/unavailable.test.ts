import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import UnavailablePage from '@/pages/UnavailablePage.vue'
import { useAuthStore } from '@/stores/auth'
import { clickByText, cleanupPage, mountPage, settle } from './helpers'

const base = {
  initialized: true,
  has_admin: true,
  authenticated: false,
  must_change_password: false,
  totp_enabled: false,
  role: 'server' as const,
  version: '0.1.2',
  public_ui: false,
}

describe('unavailable page', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
  })
  afterEach(() => cleanupPage())

  it('shows the probe error and retries to login when signed out', async () => {
    const { wrapper, router } = await mountPage(UnavailablePage, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.statusState = 'error'
      auth.error = 'probe failed'
      auth.status = { ...base }
      auth.ready = true
      auth.bootstrap = vi.fn(async () => {
        auth.statusState = 'ready'
      })
    })
    expect(wrapper.text()).toContain('probe failed')
    await clickByText('Retry')
    await settle()
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('retries to the dashboard when already authenticated', async () => {
    const { router } = await mountPage(UnavailablePage, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.statusState = 'error'
      auth.error = 'probe failed'
      auth.status = { ...base, authenticated: true }
      auth.ready = true
      auth.bootstrap = vi.fn(async () => {
        auth.statusState = 'ready'
      })
    })
    await clickByText('Retry')
    await settle()
    expect(router.currentRoute.value.path).toBe('/')
  })

  it('stays on the page while the retry is still failing', async () => {
    const { router } = await mountPage(UnavailablePage, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.statusState = 'error'
      auth.error = 'still down'
      auth.status = { ...base }
      auth.ready = true
      auth.bootstrap = vi.fn(async () => {
        auth.statusState = 'error'
      })
    })
    await clickByText('Retry')
    await settle()
    expect(router.currentRoute.value.path).toBe('/')
  })
})
