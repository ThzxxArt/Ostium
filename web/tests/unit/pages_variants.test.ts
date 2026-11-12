import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AuditPage from '@/pages/AuditPage.vue'
import JobsPage from '@/pages/JobsPage.vue'
import ConnectionsPage from '@/pages/ConnectionsPage.vue'
import ClientHomePage from '@/pages/ClientHomePage.vue'
import InboundsPage from '@/pages/InboundsPage.vue'
import LogsPage from '@/pages/LogsPage.vue'
import { api } from '@/api'
import { fixtures, installFetchMock, mountPage, settle, cleanupPage } from './helpers'

function stateOf(wrapper: any, component: any) {
  return wrapper.findComponent(component).vm.$.setupState
}

describe('page variant branches', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
  })
  afterEach(() => {
    cleanupPage()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('filters audit entries by actor, action, target and ip', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(AuditPage)
    const state = stateOf(wrapper, AuditPage)
    await settle()
    for (const needle of ['admin', 'user.created', 'alice', '127.0.0.1', 'zzz']) {
      state.search = needle
      await settle()
      expect(state.filtered.length).toBe(needle === 'zzz' ? 0 : 1)
    }
    state.search = ''
    expect(state.filtered.length).toBe(1)
    expect(wrapper.html()).toBeTruthy()
  })

  it('covers job icons, silent failures and cancellation errors', async () => {
    vi.useFakeTimers()
    installFetchMock()
    const { wrapper } = await mountPage(JobsPage)
    const state = stateOf(wrapper, JobsPage)
    await settle()
    for (const status of ['succeeded', 'failed', 'running', 'queued', 'cancelled', 'unknown']) {
      expect(state.icon(status)).toBeTruthy()
    }
    state.openDetail(fixtures.job)
    expect(state.detailOpen).toBe(true)
    await state.cancel(fixtures.job)
    vi.advanceTimersByTime(3100)

    vi.spyOn(api.jobs, 'cancel').mockRejectedValue(new Error('cancel failed'))
    await state.cancel(fixtures.job)
    vi.spyOn(api.jobs, 'list').mockRejectedValue(new Error('silent failure'))
    await state.load(true)
    expect(state.loading).toBe(false)
    expect(wrapper.html()).toBeTruthy()
  })

  it('filters connections and handles close/pause failures', async () => {
    vi.useFakeTimers()
    installFetchMock()
    const { wrapper } = await mountPage(ConnectionsPage)
    const state = stateOf(wrapper, ConnectionsPage)
    await settle()
    for (const needle of ['example', '1.2.3.4', 'curl', 'MATCH', 'zzz']) {
      state.search = needle
      expect(state.filtered.length).toBe(needle === 'zzz' ? 0 : 1)
    }
    state.search = ''
    expect(state.duration({ ...fixtures.connection, start: 'not-a-date' })).toBe('—')
    state.togglePause()
    expect(state.paused).toBe(true)
    state.togglePause()
    expect(state.paused).toBe(false)
    await state.closeConnection(fixtures.connection)
    await state.closeAll()
    vi.spyOn(api.stats, 'closeConnection').mockRejectedValue(new Error('close failed'))
    vi.spyOn(api.stats, 'closeAll').mockRejectedValue(new Error('close all failed'))
    vi.spyOn(api.stats, 'connections').mockRejectedValue(new Error('silent'))
    await state.closeConnection(fixtures.connection)
    await state.closeAll()
    await state.load(true)
    vi.advanceTimersByTime(3100)
    expect(wrapper.html()).toBeTruthy()
  })

  it('covers client home modes, selection and connection errors', async () => {
    const infoTun = {
      ...fixtures.systemInfo,
      mode: 'tun',
      core: { running: false },
    }
    installFetchMock({
      role: 'client',
      overrides: {
        '/api/v1/system/info': infoTun,
        '/api/v1/stats/connections': {
          connections: [],
          upload_total: 100,
          download_total: 200,
          unavailable: false,
        },
      },
    })
    const { wrapper } = await mountPage(ClientHomePage)
    const state = stateOf(wrapper, ClientHomePage)
    await settle()
    await state.load()
    await settle()
    expect(state.info?.mode).toBe('tun')
    expect(state.modeLabel).toContain('TUN')
    expect(state.warning).toBeTruthy()
    await state.toggleConnection()
    await state.selectProfile(fixtures.profile.id)
    await state.selectEndpoint('jp-1')
    await state.selectEndpoint('')
    state.busy = true
    await state.toggleConnection()
    state.busy = false
    vi.spyOn(api.system, 'connect').mockRejectedValue(new Error('connect failed'))
    await state.toggleConnection()
    vi.spyOn(api.profiles, 'update').mockRejectedValue(new Error('update failed'))
    await state.selectEndpoint('hk-0')
    expect(state.connectionDuration()).toBeTruthy()

    infoTun.mode = 'system_proxy'
    infoTun.core = { running: true }
    await state.load()
    expect(state.modeLabel).toContain('System')
    expect(state.connectionDuration()).not.toBe('—')
    expect(wrapper.html()).toBeTruthy()
  })

  it('renders client home without profiles', async () => {
    installFetchMock({
      role: 'client',
      mode: 'empty',
      overrides: { '/api/v1/stats/connections': [], '/api/v1/system/info': fixtures.systemInfo },
    })
    const { wrapper } = await mountPage(ClientHomePage)
    await settle()
    expect(wrapper.text()).toContain('profile')
  })

  it('renders inbound variants with certificates and warning/error paths', async () => {
    const variant = fixtures.inbounds.map((inbound, index) => ({
      ...inbound,
      enabled: index < 2,
      certificate: index === 1 ? fixtures.certificate : null,
      params: {
        public_key: index === 0 ? 'pub' : null,
        short_id: index === 0 ? 'sid' : null,
        server_name: index === 0 ? 'sni' : null,
        handshake_server: index === 0 ? 'sni' : null,
        handshake_port: index === 0 ? 443 : null,
        has_obfs: index === 1,
        has_server_key: index === 3,
      },
    }))
    installFetchMock({ overrides: { '/api/v1/inbounds': { inbounds: variant } } })
    const { wrapper } = await mountPage(InboundsPage)
    const state = stateOf(wrapper, InboundsPage)
    await settle()
    expect(wrapper.html()).toBeTruthy()
    expect(state.protocolIcon(fixtures.inbounds[0])).toBeTruthy()
    expect(state.protocolIcon({ ...fixtures.inbounds[0], kind: 'unknown' as any })).toBeTruthy()
    vi.spyOn(api.inbounds, 'update').mockResolvedValueOnce({
      inbound: variant[0],
      applied: false,
      warning: 'saved but not applied',
    })
    await state.toggle(variant[0], true)
    expect(state.warning).toBe('saved but not applied')
    vi.spyOn(api.inbounds, 'update').mockRejectedValueOnce(new Error('toggle failed'))
    await state.toggle(variant[0], false)
    state.confirmRotate(variant[0])
    vi.spyOn(api.inbounds, 'rotateReality').mockRejectedValueOnce(new Error('rotate failed'))
    state.confirmRotate(variant[0])
    expect(wrapper.html()).toBeTruthy()
  })

  it('renders a core logs unavailable state', async () => {
    installFetchMock({
      overrides: {
        '/api/v1/logs': {
          source: 'core',
          records: [],
          lines: [],
          unavailable: true,
          error: 'core is down',
        },
      },
    })
    const { wrapper } = await mountPage(LogsPage)
    const state = stateOf(wrapper, LogsPage)
    await settle()
    state.source = 'core'
    await settle()
    expect(wrapper.text()).toContain('core is down')
    state.source = 'ostium'
    await settle()
    expect(wrapper.html()).toBeTruthy()
  })
})
