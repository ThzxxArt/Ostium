import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import ClientHomePage from '@/pages/ClientHomePage.vue'
import ProfilesPage from '@/pages/ProfilesPage.vue'
import RoutingPage from '@/pages/RoutingPage.vue'
import NetworkPage from '@/pages/NetworkPage.vue'
import StatsPage from '@/pages/StatsPage.vue'
import DiagnosticsPage from '@/pages/DiagnosticsPage.vue'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api'
import { vi } from 'vitest'
import {
  cleanupPage,
  clickAllButtons,
  fixtures,
  installFetchMock,
  mountPage,
  settle,
} from './helpers'

function stateOf(wrapper: any, component: any) {
  return wrapper.findComponent(component).vm.$.setupState
}

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

  it('ClientHomePage activates the selected profile', async () => {
    const second = { ...fixtures.profile, id: 'profile-2', name: 'JP' }
    installFetchMock({
      role: 'client',
      overrides: {
        '/api/v1/profiles': {
          profiles: [fixtures.profile, second],
          active_profile_id: fixtures.profile.id,
        },
      },
    })
    const activate = vi.spyOn(api.profiles, 'activate').mockResolvedValueOnce({
      profile: second,
      applied: true,
    })
    vi.spyOn(api.profiles, 'update').mockResolvedValueOnce({ profile: second, applied: true })
    const { wrapper } = await mountPage(ClientHomePage)
    await settle()
    const state = stateOf(wrapper, ClientHomePage)
    await state.selectProfile('profile-2')
    await settle()
    expect(activate).toHaveBeenCalledWith('profile-2')
  })

  it('ClientHomePage shows auto-select instead of pinning the first endpoint', async () => {
    const profile = { ...fixtures.profile, selected_endpoint: null }
    installFetchMock({
      role: 'client',
      overrides: {
        '/api/v1/profiles': { profiles: [profile], active_profile_id: profile.id },
      },
    })
    const update = vi.spyOn(api.profiles, 'update')
    const { wrapper } = await mountPage(ClientHomePage)
    await settle()
    const state = stateOf(wrapper, ClientHomePage)
    expect(state.selectedEndpoint).toBeNull()
    await state.selectProfile(profile.id)
    await settle()
    expect(update).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Auto-select fastest')
  })

  it('ClientHomePage displays the configured mixed port', async () => {
    installFetchMock({
      role: 'client',
      overrides: {
        '/api/v1/system/info': { ...fixtures.systemInfo, mixed_port: 8123 },
      },
    })
    const { wrapper } = await mountPage(ClientHomePage)
    await settle()
    expect(wrapper.text()).toContain('8123')
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
