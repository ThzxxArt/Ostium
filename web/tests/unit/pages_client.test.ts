import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import ClientHomePage from '@/pages/ClientHomePage.vue'
import ProfilesPage from '@/pages/ProfilesPage.vue'
import RoutingPage from '@/pages/RoutingPage.vue'
import NetworkPage from '@/pages/NetworkPage.vue'
import StatsPage from '@/pages/StatsPage.vue'
import DiagnosticsPage from '@/pages/DiagnosticsPage.vue'
import { useAuthStore } from '@/stores/auth'
import {
  cleanupPage,
  clickAllButtons,
  fixtures,
  installFetchMock,
  mountPage,
  settle,
} from './helpers'

const pages = [
  ['ClientHomePage', ClientHomePage],
  ['ProfilesPage', ProfilesPage],
  ['RoutingPage', RoutingPage],
  ['NetworkPage', NetworkPage],
  ['StatsPage', StatsPage],
  ['DiagnosticsPage', DiagnosticsPage],
] as const

describe('client pages', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
    localStorage.clear()
  })
  afterEach(() => cleanupPage())

  it.each(pages)('%s renders with client data and actions', async (_name, page) => {
    installFetchMock({ role: 'client' })
    const { wrapper } = await mountPage(page)
    await settle()
    expect(wrapper.html()).toBeTruthy()
    await clickAllButtons(1)
    expect(wrapper.html()).toBeTruthy()
  })

  it.each(pages)('%s shows error state', async (_name, page) => {
    installFetchMock({ role: 'client', mode: 'error' })
    const { wrapper } = await mountPage(page)
    await settle()
    await clickAllButtons(1)
    expect(wrapper.html()).toBeTruthy()
  })

  it.each(pages)('%s handles empty data', async (_name, page) => {
    installFetchMock({ role: 'client', mode: 'empty' })
    const { wrapper } = await mountPage(page)
    await settle()
    expect(wrapper.html()).toBeTruthy()
  })

  it('NetworkPage shows LAN proxy addresses when allow_lan is enabled', async () => {
    installFetchMock({
      role: 'client',
      overrides: {
        '/api/v1/system/info': {
          ...fixtures.systemInfo,
          allow_lan: true,
          lan_addresses: ['192.168.1.10'],
          lan_port: 7890,
        },
      },
    })
    const { wrapper } = await mountPage(NetworkPage)
    await settle()
    expect(wrapper.text()).toContain('Allow LAN connections')
    expect(wrapper.text()).toContain('192.168.1.10:7890')
  })

  it('HomeGate renders the client home for client roles', async () => {
    installFetchMock({ role: 'client' })
    const { wrapper } = await mountPage(
      (await import('@/pages/HomeGate.vue')).default,
      {},
      (pinia) => {
        const auth = useAuthStore(pinia)
        auth.status = {
          initialized: true,
          has_admin: true,
          authenticated: true,
          must_change_password: false,
          totp_enabled: false,
          role: 'client',
          version: '0.1.0',
          public_ui: false,
        }
      },
    )
    await settle()
    expect(wrapper.text()).toContain('Home')
  })
})
