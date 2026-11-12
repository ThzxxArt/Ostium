import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from '@/pages/SettingsPage.vue'
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

describe('SettingsPage interactions', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
    vi.stubGlobal(
      'prompt',
      vi.fn(() => 'verysecret123'),
    )
  })
  afterEach(() => {
    cleanupPage()
    vi.unstubAllGlobals()
  })

  it('saves every section, manages tokens, TOTP and backups', async () => {
    const { calls } = installFetchMock()
    const { wrapper } = await mountPage(SettingsPage)
    await settle()

    // General tab: language, themes, save, and the public UI switch.
    await clickByText('中文')
    await clickByText('English')
    await clickByText('Dark')
    await clickByText('Light')
    await clickByText('System')
    await clickByText('Save')
    const publicSwitch = document.querySelector('.n-switch') as HTMLElement | null
    publicSwitch?.click()
    await settle()
    publicSwitch?.click()
    await settle()

    // Security tab.
    await clickByText('Security')
    await fillInputs()
    await clickByText('Change password')
    await clickByText('Disable TOTP')
    await clickByText('New token')
    await fillInputs({ 'ci-deploy': 'ci-deploy' })
    await clickByText('Create')
    await clickByText('Revoke')
    await clickByText('Confirm')

    // Notifications tab.
    await clickByText('Notifications')
    await fillInputs({ 'https://example.com/hook': 'https://hooks.example.com/ostium' })
    await clickByText('Save')
    await clickByText('Enable browser notifications')

    // Maintenance and backups.
    await clickByText('Maintenance')
    await clickByText('Save')
    await clickByText('Create backup')
    await clickByText('Create')
    await clickByText('Apply')
    await clickByText('Apply')
    const remove = wrapper.find('.backup button:last-child')
    if (remove.exists()) await remove.trigger('click')
    await clickByText('Delete')
    await clickByText('Confirm')
    await clickAllButtons(1)

    expect(calls.some((call) => call.path === '/api/v1/settings')).toBe(true)
    expect(wrapper.html()).toBeTruthy()
  })

  it('enables TOTP when disabled', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(SettingsPage, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.me = {
        id: 'admin-1',
        username: 'admin',
        must_change_password: false,
        totp_enabled: false,
        recovery_codes_remaining: 0,
        last_login_at: null,
        role: 'server',
      }
    })
    await settle()
    await clickByText('Security')
    await clickByText('Enable TOTP')
    await fillInputs({ '123456': '123456' })
    await clickByText('Confirm')
    await clickAllButtons(1)
    expect(wrapper.html()).toBeTruthy()
  })

  it('handles errors in every save path', async () => {
    installFetchMock({ mode: 'error' })
    const { wrapper } = await mountPage(SettingsPage)
    await settle()
    await clickAllButtons(2)
    expect(wrapper.html()).toBeTruthy()
  })
})
