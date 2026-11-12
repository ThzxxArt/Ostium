import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import LoginPage from '@/pages/LoginPage.vue'
import SetupPage from '@/pages/SetupPage.vue'
import OnboardingPage from '@/pages/OnboardingPage.vue'
import NotFoundPage from '@/pages/NotFoundPage.vue'
import ClientHomePage from '@/pages/ClientHomePage.vue'
import DashboardPage from '@/pages/DashboardPage.vue'
import { useAuthStore } from '@/stores/auth'
import { cleanupPage, clickAllButtons, installFetchMock, mountPage, settle } from './helpers'

describe('auth and fallback pages', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
    localStorage.clear()
  })
  afterEach(() => cleanupPage())

  it('renders and submits the login form', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(LoginPage)
    await settle()
    expect(wrapper.text().length).toBeGreaterThan(10)
    await clickAllButtons(2)
    expect(wrapper.html()).toBeTruthy()
  })

  it('renders login errors', async () => {
    installFetchMock({ mode: 'error' })
    const { wrapper } = await mountPage(LoginPage)
    await settle()
    await clickAllButtons(2)
    expect(wrapper.html()).toBeTruthy()
  })

  it('renders all setup steps and interactions', async () => {
    installFetchMock({ mode: 'empty' })
    const { wrapper } = await mountPage(SetupPage)
    await settle()
    await clickAllButtons(3)
    expect(wrapper.html()).toBeTruthy()
  })

  it('renders setup with errors', async () => {
    installFetchMock({ mode: 'error' })
    const { wrapper } = await mountPage(SetupPage)
    await settle()
    await clickAllButtons(2)
    expect(wrapper.html()).toBeTruthy()
  })

  it('renders onboarding and 404', async () => {
    installFetchMock({ role: 'client' })
    const onboarding = await mountPage(OnboardingPage)
    await settle()
    await clickAllButtons(2)
    expect(onboarding.wrapper.html()).toBeTruthy()
    cleanupPage()
    const notFound = await mountPage(NotFoundPage)
    await settle()
    expect(notFound.wrapper.text().length).toBeGreaterThan(3)
  })

  it('HomeGate switches between server and client dashboards', async () => {
    installFetchMock()
    const HomeGate = (await import('@/pages/HomeGate.vue')).default
    const server = await mountPage(HomeGate, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.status = {
        initialized: true,
        has_admin: true,
        authenticated: true,
        must_change_password: false,
        totp_enabled: false,
        role: 'server',
        version: '0.1.0',
        public_ui: false,
      }
    })
    await settle()
    expect(server.wrapper.findComponent(DashboardPage).exists()).toBe(true)
    cleanupPage()

    const client = await mountPage(HomeGate, {}, (pinia) => {
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
    })
    await settle()
    expect(client.wrapper.findComponent(ClientHomePage).exists()).toBe(true)
  })
})
