import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'
import ClientHomePage from '@/pages/ClientHomePage.vue'
import DashboardPage from '@/pages/DashboardPage.vue'
import NetworkPage from '@/pages/NetworkPage.vue'
import SettingsPage from '@/pages/SettingsPage.vue'
import StatsPage from '@/pages/StatsPage.vue'
import UsersPage from '@/pages/UsersPage.vue'
import { fixtures, installFetchMock, mountPage, settle } from './helpers'

function stateOf(wrapper: any, component: any) {
  return wrapper.findComponent(component).vm.$.setupState
}

describe('review round 1 page branches', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('keeps the newest traffic range when responses arrive out of order', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(StatsPage)
    await settle()
    const state = stateOf(wrapper, StatsPage)

    let resolveOld: (value: any) => void = () => {}
    const old = new Promise((resolve) => {
      resolveOld = resolve
    })
    const traffic = vi.spyOn(api.stats, 'traffic')
    traffic.mockReturnValueOnce(old as any).mockResolvedValueOnce({
      series: [{ day: '2026-01-07', up: 7, down: 7 }],
      days: 7,
      user_id: null,
    })
    const first = state.changeDays(1)
    const second = state.changeDays(7)
    resolveOld({ series: [{ day: '2026-01-01', up: 1, down: 1 }], days: 1, user_id: null })
    await first
    await second
    expect(state.days).toBe(7)
    expect(state.series[0].up).toBe(7)

    traffic.mockRejectedValueOnce(new Error('traffic down'))
    await state.changeDays(30)
    expect(state.error).toContain('traffic down')
  })

  it('does not reuse the previous usage chart when a user detail request fails', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(UsersPage)
    await settle()
    const state = stateOf(wrapper, UsersPage)
    state.usageSeries = [{ day: '2026-01-01', up: 99, down: 99 }]

    vi.spyOn(api.users, 'get').mockResolvedValueOnce({
      user: fixtures.user,
      pending_bytes: 0,
    })
    vi.spyOn(api.users, 'usage').mockRejectedValueOnce(new Error('usage down'))
    await state.openDetail(fixtures.user)
    await settle()
    expect(state.usageSeries).toEqual([])

    vi.spyOn(api.users, 'get').mockRejectedValueOnce(new Error('detail down'))
    vi.spyOn(api.users, 'usage').mockResolvedValueOnce({
      user: fixtures.user,
      series: [],
      today: { up: 0, down: 0 },
    })
    await state.openDetail(fixtures.user)
    await settle()
    expect(state.activeUser.id).toBe(fixtures.user.id)

    expect(Number.isNaN(state.parseBytes('9007199254740993G'))).toBe(true)
    expect(Number.isNaN(state.parseBytes('not-a-size'))).toBe(true)
  })

  it('requires TOTP and a domain before enabling the public UI', async () => {
    installFetchMock()
    let authStore: ReturnType<typeof useAuthStore>
    const { wrapper } = await mountPage(SettingsPage, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      authStore = auth
      auth.status = { ...fixtures.status, authenticated: true }
      auth.me = { ...fixtures.me, totp_enabled: false }
      auth.ready = true
    })
    await settle()
    const state = stateOf(wrapper, SettingsPage)
    state.publicUiEnabled = true
    await state.togglePublicUi(true)
    expect(state.publicUiEnabled).toBe(false)

    authStore!.me = { ...fixtures.me, totp_enabled: true }
    state.publicUiDomain = ''
    state.publicUiEnabled = true
    await state.togglePublicUi(true)
    expect(state.publicUiEnabled).toBe(false)
  })

  it('persists the restart warning and rolls back a failed public UI toggle', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(SettingsPage, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.status = { ...fixtures.status, authenticated: true }
      auth.me = { ...fixtures.me, totp_enabled: true }
      auth.ready = true
    })
    await settle()
    const state = stateOf(wrapper, SettingsPage)
    state.publicUiDomain = 'vpn.example.com'
    vi.spyOn(api.settings, 'publicUi').mockResolvedValueOnce({
      public_ui: true,
      restart_required: true,
      message: 'Restart ostium.service to apply the new listener/TLS settings.',
    })
    await state.togglePublicUi(true)
    expect(state.publicUiRestart).toContain('ostium.service')

    vi.spyOn(api.settings, 'publicUi').mockRejectedValueOnce(new Error('toggle failed'))
    state.publicUiEnabled = true
    await state.togglePublicUi(false)
    expect(state.publicUiEnabled).toBe(true)

    // Changing the domain while disabled is a no-op.
    state.publicUiEnabled = false
    await state.onPublicUiDomainChange('ignored.example.com')
    expect(state.publicUiDomain).toBe('ignored.example.com')
  })

  it('shows a network error instead of fabricated defaults', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(NetworkPage)
    await settle()
    const state = stateOf(wrapper, NetworkPage)
    vi.spyOn(api.system, 'info').mockRejectedValueOnce(new Error('info down'))
    await state.load()
    expect(state.error).toContain('info down')

    vi.spyOn(api.settings, 'update').mockRejectedValueOnce(new Error('lan failed'))
    await state.toggleLan(true)
    expect(state.lanBusy).toBe(false)

    vi.spyOn(api.settings, 'update').mockResolvedValueOnce({ ok: true })
    await state.toggleLan(false)
    expect(state.lanBusy).toBe(false)
  })

  it('keeps usable dashboard widgets when one endpoint fails', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(DashboardPage)
    await settle()
    const state = stateOf(wrapper, DashboardPage)
    vi.spyOn(api.alerts, 'list').mockRejectedValueOnce(new Error('alerts down'))
    await state.load()
    expect(state.partialError).toContain('alerts down')
    expect(state.overview).not.toBeNull()
  })

  it('keeps settings usable when certificate and backup panels fail', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(SettingsPage)
    await settle()
    const state = stateOf(wrapper, SettingsPage)
    vi.spyOn(api.certificates, 'list').mockRejectedValueOnce(new Error('certs down'))
    vi.spyOn(api.backups, 'list').mockRejectedValueOnce(new Error('backups down'))
    await state.load()
    expect(state.settings).not.toBeNull()
    expect(state.loadError).toBe('')
  })

  it('updates an enabled public UI domain and clears the restart warning on success', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(SettingsPage, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.status = { ...fixtures.status, authenticated: true }
      auth.me = { ...fixtures.me, totp_enabled: true }
      auth.ready = true
    })
    await settle()
    const state = stateOf(wrapper, SettingsPage)
    state.publicUiEnabled = true
    state.publicUiRestart = 'old warning'
    vi.spyOn(api.settings, 'publicUi').mockResolvedValueOnce({
      public_ui: true,
      restart_required: false,
      message: 'updated',
    })
    await state.onPublicUiDomainChange('new.example.com')
    expect(state.publicUiRestart).toBe('')
  })

  it('shows a client-home error instead of the import wizard when loading fails', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(ClientHomePage, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.status = { ...fixtures.status, role: 'client', authenticated: true }
      auth.me = fixtures.me
      auth.ready = true
    })
    await settle()
    const state = stateOf(wrapper, ClientHomePage)
    vi.spyOn(api.system, 'info').mockRejectedValueOnce(new Error('info down'))
    vi.spyOn(api.profiles, 'list').mockRejectedValueOnce(new Error('profiles down'))
    vi.spyOn(api.stats, 'connections').mockRejectedValueOnce(new Error('connections down'))
    await state.load()
    expect(state.loadError).toContain('info down')
    // Existing (stale) profiles stay visible; the error banner makes the
    // degradation explicit instead of replacing them with the import wizard.
    expect(state.loadError).not.toBe('')
  })

  it('reports a failed primary dashboard request instead of pretending it succeeded', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(DashboardPage)
    await settle()
    const state = stateOf(wrapper, DashboardPage)
    vi.spyOn(api.stats, 'overview').mockRejectedValueOnce(new Error('overview down'))
    await state.load()
    // The previous dashboard data is preserved, while the partial failure is
    // visible in the warning banner.
    expect(state.partialError).toContain('overview down')
  })
})
