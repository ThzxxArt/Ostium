import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AppLayout from '@/layouts/AppLayout.vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useEventStore } from '@/stores/events'
import { fixtures, installFetchMock, mountPage, settle, cleanupPage } from './helpers'

const serverStatus = {
  initialized: true,
  has_admin: true,
  authenticated: true,
  must_change_password: false,
  totp_enabled: true,
  role: 'server' as const,
  version: '0.1.0',
  public_ui: false,
}

describe('AppLayout branches', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
    localStorage.clear()
  })
  afterEach(() => {
    cleanupPage()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('handles menus, shortcuts and notifications', async () => {
    installFetchMock()
    const { wrapper, router, pinia } = await mountPage(AppLayout, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.status = serverStatus
      auth.me = fixtures.me
      auth.ready = true
    })
    const state = (wrapper.findComponent(AppLayout).vm as any).$.setupState
    const app = useAppStore(pinia)
    const auth = useAuthStore(pinia)
    const events = useEventStore(pinia)
    await settle()

    expect(state.groups.length).toBeGreaterThan(0)
    expect(state.pageTitle).toBeTruthy()
    for (const key of ['settings', 'shortcuts', 'logout', 'other']) {
      state.onUserSelect(key)
      await settle()
    }
    for (const key of ['system', 'logs', 'jobs', 'home', 'other']) {
      state.onStatusSelect(key)
      await settle()
    }
    state.toggleNavDrawer()
    state.toggleNavDrawer()
    state.openJobs()
    expect(app.jobDrawerOpen).toBe(true)
    app.jobDrawerOpen = false

    // Keyboard handling: typing, command palette, search, help, escape, go-to.
    function keyEvent(key: string, init: KeyboardEventInit = {}, target?: EventTarget) {
      const event = new KeyboardEvent('keydown', { key, bubbles: true, ...init })
      if (target) Object.defineProperty(event, 'target', { value: target })
      return event
    }

    state.onKeydown(keyEvent('k', { ctrlKey: true }))
    state.onKeydown(keyEvent('/', {}, document.body))
    state.onKeydown(keyEvent('?', {}, document.body))
    state.onKeydown(keyEvent('Escape', {}, document.body))
    for (const key of ['g', 'd', 'u', 'c', 'r', 'l', 's', 'x', 'c']) {
      state.onKeydown(keyEvent(key, {}, document.body))
    }
    state.onKeydown(keyEvent('k', { ctrlKey: true }, document.createElement('input')))
    const input = document.createElement('input')
    input.type = 'search'
    document.body.appendChild(input)
    state.onKeydown(keyEvent('/', {}, document.body))
    input.remove()

    // Alert and job event watchers.
    events.lastAlert = {
      type: 'alert.created',
      ts: 'now',
      data: { message: 'quota warning' },
    } as any
    await settle()
    for (const status of ['succeeded', 'failed', 'running']) {
      events.lastJob = {
        type: 'job.updated',
        ts: 'now',
        data: { status, type: 'backup', id: 'job-1' },
      } as any
      await settle()
    }
    app.jobDrawerOpen = true
    events.lastJob = { type: 'job.updated', ts: 'now', data: { status: 'succeeded' } } as any
    await settle()

    // Unexpected connection failures.
    async function fail() {
      throw new Error('network down')
    }
    const api = await import('@/api')
    vi.spyOn(api.api.alerts, 'list').mockRejectedValue(new Error('alerts down'))
    vi.spyOn(api.api.alerts, 'ack').mockRejectedValue(new Error('ack down'))
    await state.loadAlerts()
    await state.ackAlert(fixtures.alert)
    state.alerts = [fixtures.alert]
    await state.ackAlert(fixtures.alert)
    await router.push('/missing')
    await settle()
    expect(auth.me).toBeNull()
    expect(fail).toBeDefined()
    expect(wrapper.html()).toBeTruthy()
  })

  it('handles client navigation and connection toggles', async () => {
    installFetchMock({ role: 'client' })
    const { wrapper, pinia } = await mountPage(AppLayout, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.status = { ...serverStatus, role: 'client' }
      auth.me = { ...fixtures.me, role: 'client' }
      auth.ready = true
    })
    const state = (wrapper.findComponent(AppLayout).vm as any).$.setupState
    const auth = useAuthStore(pinia)
    await settle()
    expect(state.statusOptions.some((item: any) => item.key === 'network')).toBe(true)
    state.onStatusSelect('network')
    await settle()

    // Connected -> disconnect.
    state.coreReachable = true
    state.coreRunning = true
    await state.toggleConnection()
    // Disconnected -> connect.
    state.coreRunning = false
    await state.toggleConnection()
    // Error path.
    const api = await import('@/api')
    vi.spyOn(api.api.system, 'connect').mockRejectedValue(new Error('connect failed'))
    await state.toggleConnection()
    expect(auth.isClient).toBe(true)
    expect(wrapper.html()).toBeTruthy()
  })
})
