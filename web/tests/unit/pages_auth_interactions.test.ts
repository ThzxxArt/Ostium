import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LoginPage from '@/pages/LoginPage.vue'
import SetupPage from '@/pages/SetupPage.vue'
import { useAuthStore } from '@/stores/auth'
import {
  cleanupPage,
  clickAllButtons,
  clickByText,
  fillInputs,
  installFetchMock,
  mountPage,
  settle,
} from './helpers'

const status = (role: 'server' | 'client') => ({
  initialized: false,
  has_admin: false,
  authenticated: false,
  must_change_password: false,
  totp_enabled: false,
  role,
  version: '0.1.0',
  public_ui: false,
})

describe('auth page interactions', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
    localStorage.clear()
  })
  afterEach(() => cleanupPage())

  it('walks the full server setup wizard', async () => {
    const { calls } = installFetchMock({ mode: 'empty' })
    const { wrapper } = await mountPage(SetupPage, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.status = status('server')
      auth.ready = true
    })
    await settle()

    // Validation errors, then a valid account.
    await clickByText('Next')
    await (wrapper.vm as any).$?.setupState?.next?.()
    await settle()
    await fillInputs()
    await clickByText('Next')
    await fillInputs({ 'vpn.example.com': 'vpn.example.com' })
    await clickByText('Next')
    await clickByText('Hysteria2')
    await clickByText('Reality + Hysteria2')
    await clickByText('Next')
    await clickByText('Previous')
    await clickByText('Next')
    const checkbox = document.querySelector('.n-checkbox') as HTMLElement | null
    checkbox?.click()
    await settle()
    await clickByText('Create')
    expect(calls.some((call) => call.path === '/api/v1/setup')).toBe(true)
    expect(wrapper.html()).toBeTruthy()
  })

  it('walks the client setup wizard', async () => {
    const { calls } = installFetchMock({ role: 'client', mode: 'empty' })
    const { wrapper } = await mountPage(SetupPage, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.status = status('client')
      auth.ready = true
    })
    await settle()
    await fillInputs()
    await clickByText('Next')
    await fillInputs()
    await clickByText('Next')
    await clickByText('TUN')
    await clickByText('Mixed')
    await clickByText('Finish')
    expect(calls.some((call) => call.path === '/api/v1/setup')).toBe(true)
    await clickAllButtons(1)
    expect(wrapper.html()).toBeTruthy()
  })

  it('imports a subscription URL through the URL field during client setup', async () => {
    const { calls } = installFetchMock({ role: 'client', mode: 'empty' })
    const { wrapper } = await mountPage(SetupPage, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.status = status('client')
      auth.ready = true
    })
    await settle()
    const state = (wrapper.findComponent(SetupPage).vm as any).$.setupState
    state.password = 'verysecret123'
    state.confirm = 'verysecret123'
    state.importText = 'https://vpn.example.com/sub/token'
    await state.finish()
    await settle()
    const created = calls.find((call) => call.path === '/api/v1/profiles' && call.method === 'POST')
    expect(created?.body?.url).toBe('https://vpn.example.com/sub/token')
    expect(created?.body?.text).toBeUndefined()
  })

  it('logs in and shows validation errors', async () => {
    const { calls } = installFetchMock()
    const { wrapper } = await mountPage(LoginPage)
    await settle()
    await clickAllButtons(1)
    await fillInputs({ Username: 'admin', Password: 'verysecret123' })
    await clickByText('Sign in')
    expect(calls.some((call) => call.path === '/api/v1/auth/login')).toBe(true)
    await clickByText('中')
    await clickAllButtons(1)
    expect(wrapper.html()).toBeTruthy()
  })

  it('shows TOTP and rate-limit errors', async () => {
    const responses = [
      {
        status: 401,
        body: { detail: 'totp', code: 'totp_required' },
      },
      {
        status: 429,
        body: { detail: 'slow', code: 'rate_limited' },
      },
      {
        status: 500,
        body: { detail: 'broken', code: 'internal_error' },
      },
    ]
    let loginCalls = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), 'http://localhost').pathname
        if (path === '/api/v1/auth/login') {
          const item = responses[Math.min(loginCalls++, responses.length - 1)]
          return {
            ok: false,
            status: item.status,
            headers: new Headers({ 'content-type': 'application/problem+json' }),
            json: async () => item.body,
            text: async () => JSON.stringify(item.body),
          }
        }
        if (path === '/api/v1/auth/status') {
          return {
            ok: true,
            status: 200,
            headers: new Headers({ 'content-type': 'application/json' }),
            json: async () => ({
              initialized: true,
              has_admin: true,
              authenticated: false,
              must_change_password: false,
              totp_enabled: true,
              role: 'server',
              version: '0.1.0',
              public_ui: false,
            }),
            text: async () => '{}',
          }
        }
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({}),
          text: async () => '{}',
        }
      }),
    )
    const { wrapper } = await mountPage(LoginPage, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.ready = true
      auth.status = {
        ...status('server'),
        initialized: true,
        has_admin: true,
        totp_enabled: true,
      }
    })
    await settle()
    await fillInputs({ Username: 'admin', Password: 'verysecret123' })
    await clickByText('Sign in')
    expect(document.querySelector('input[placeholder="123456"]')).toBeTruthy()
    await clickByText('Sign in')
    await clickByText('Sign in')
    expect(wrapper.html()).toBeTruthy()
    vi.unstubAllGlobals()
  })
})
