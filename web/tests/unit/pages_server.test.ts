import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import DashboardPage from '@/pages/DashboardPage.vue'
import InboundsPage from '@/pages/InboundsPage.vue'
import UsersPage from '@/pages/UsersPage.vue'
import SubscriptionsPage from '@/pages/SubscriptionsPage.vue'
import ConnectionsPage from '@/pages/ConnectionsPage.vue'
import RulesPage from '@/pages/RulesPage.vue'
import CertificatesPage from '@/pages/CertificatesPage.vue'
import LogsPage from '@/pages/LogsPage.vue'
import JobsPage from '@/pages/JobsPage.vue'
import SystemPage from '@/pages/SystemPage.vue'
import AuditPage from '@/pages/AuditPage.vue'
import SettingsPage from '@/pages/SettingsPage.vue'
import { cleanupPage, clickAllButtons, installFetchMock, mountPage, settle } from './helpers'

function stateOf(wrapper: any, component: any) {
  return wrapper.findComponent(component).vm.$.setupState
}

const pages = [
  ['DashboardPage', DashboardPage],
  ['InboundsPage', InboundsPage],
  ['UsersPage', UsersPage],
  ['SubscriptionsPage', SubscriptionsPage],
  ['ConnectionsPage', ConnectionsPage],
  ['RulesPage', RulesPage],
  ['CertificatesPage', CertificatesPage],
  ['LogsPage', LogsPage],
  ['JobsPage', JobsPage],
  ['SystemPage', SystemPage],
  ['AuditPage', AuditPage],
  ['SettingsPage', SettingsPage],
] as const

describe('server pages', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
    localStorage.clear()
  })
  afterEach(() => {
    cleanupPage()
  })

  it.each(pages)('%s renders with data and handles its primary actions', async (_name, page) => {
    installFetchMock()
    const { wrapper } = await mountPage(page)
    await settle()
    expect(wrapper.text().length).toBeGreaterThan(10)
    await clickAllButtons(1)
    expect(wrapper.html()).toBeTruthy()
  })

  it('SettingsPage shows build provenance and version mismatches', async () => {
    installFetchMock({
      overrides: {
        '/api/v1/system/provenance': {
          app: {
            version: '0.1.11',
            commit: 'abc123',
            built_at: '2026-11-17T00:00:00+00:00',
            frozen: false,
            executable: '/usr/bin/ostium',
            argv: [],
            pid: 42,
            process_started_at: null,
            python: '3.13.5',
            prefix: '/usr',
            package_path: '/usr/lib/ostium',
            dist_info_path: null,
            version_source: 'version_file',
          },
          web: { available: true, version: '0.1.10', built_at: '2026-11-16T00:00:00+00:00' },
          core: { reachable: true, running: true, version: '0.1.11', engine_version: '1.14.4' },
          listener: { port: 8443, host: '127.0.0.1', found: true, pid: 42, exe: '/usr/bin/ostium' },
          consistency: {
            ok: false,
            expected_version: '0.1.11',
            mismatches: [{ surface: 'web', expected: '0.1.11', actual: '0.1.10' }],
          },
          generated_at: '2026-11-17T00:00:00+00:00',
        },
      },
    })
    const { wrapper } = await mountPage(SettingsPage)
    await settle()
    const state = stateOf(wrapper, SettingsPage)
    state.activeTab = 'about'
    await settle()
    expect(wrapper.text()).toContain('0.1.11')
    expect(wrapper.text()).toContain('abc123')
    expect(wrapper.text()).toContain('Version mismatch')
    expect(wrapper.text()).toContain('web=0.1.10')
  })

  it('makes the scrollable log region keyboard focusable', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(LogsPage)
    await settle()
    const body = wrapper.find('.log-body')
    expect(body.exists()).toBe(true)
    expect(body.attributes('tabindex')).toBe('0')
    expect(body.attributes('role')).toBe('log')
  })

  it.each(pages)('%s shows error state', async (_name, page) => {
    installFetchMock({ mode: 'error' })
    const { wrapper } = await mountPage(page)
    await settle()
    expect(wrapper.text().length).toBeGreaterThan(5)
    await clickAllButtons(1)
    expect(wrapper.html()).toBeTruthy()
  })

  it.each(pages)('%s handles empty data', async (_name, page) => {
    installFetchMock({ mode: 'empty' })
    const { wrapper } = await mountPage(page)
    await settle()
    expect(wrapper.html()).toBeTruthy()
  })
})
