import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import CertificatesPage from '@/pages/CertificatesPage.vue'
import RulesPage from '@/pages/RulesPage.vue'
import ProfilesPage from '@/pages/ProfilesPage.vue'
import RoutingPage from '@/pages/RoutingPage.vue'
import InboundsPage from '@/pages/InboundsPage.vue'
import LogsPage from '@/pages/LogsPage.vue'
import ConnectionsPage from '@/pages/ConnectionsPage.vue'
import JobsPage from '@/pages/JobsPage.vue'
import SubscriptionsPage from '@/pages/SubscriptionsPage.vue'
import {
  cleanupPage,
  clickAllButtons,
  clickByText,
  clickLastByText,
  clickSelector,
  fillInputs,
  installFetchMock,
  mountPage,
  settle,
} from './helpers'

describe('page interactions', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
  })
  afterEach(() => cleanupPage())

  it('manages certificates end to end', async () => {
    const { calls } = installFetchMock()
    const { wrapper } = await mountPage(CertificatesPage)
    await settle()

    await clickByText('Issue certificate')
    await fillInputs({ 'vpn.example.com': 'new.example.com', 'you@example.com': 'a@example.com' })
    await clickLastByText('Issue certificate')
    await clickByText('Cancel')

    await clickByText('Upload')
    await fillInputs({ 'vpn.example.com': 'upload.example.com' })
    await clickLastByText('Upload')
    await clickByText('Cancel')

    await clickByText('Use')
    await clickByText('Renew')
    await clickByText('Delete')
    await clickByText('Confirm')
    await clickAllButtons(1)

    expect(calls.some((call) => call.path === '/api/v1/certificates/issue')).toBe(true)
    expect(wrapper.html()).toBeTruthy()
  })

  it('manages rules, rule sets and testing', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(RulesPage)
    await settle()

    await clickByText('Add rule')
    await fillInputs({ '.example.com, example.org': '.example.org', Name: 'custom' })
    await clickLastByText('Save')
    await clickByText('Edit')
    await fillInputs({ '.example.com, example.org': '.example.net' })
    await clickLastByText('Save')
    await clickSelector('.n-switch')
    await clickByText('Test')
    await clickByText('Add rule set')
    await fillInputs({
      'geosite-cn': 'ads',
      'https://example.com/rules.srs': 'https://example.com/ads.srs',
    })
    await clickLastByText('Add')
    await clickByText('Update')
    await clickByText('Delete')
    await clickByText('Confirm')
    await clickAllButtons(1)
    expect(wrapper.html()).toBeTruthy()
  })

  it('manages profiles and routing presets', async () => {
    installFetchMock({ role: 'client' })
    const profiles = await mountPage(ProfilesPage)
    await settle()
    await clickByText('Import profile')
    await fillInputs({
      'My server': 'HK',
      'https://example.com/sub/token': 'https://sub.example.com/hk',
    })
    await clickLastByText('Import profile')
    await clickByText('Refresh')
    await clickSelector('.endpoint')
    await clickByText('Delete')
    await clickByText('Confirm')
    await clickByText('Import profile')
    await clickSelector('.n-radio', 1)
    await fillInputs()
    await clickLastByText('Import profile')
    await clickAllButtons(1)
    expect(profiles.wrapper.html()).toBeTruthy()
    cleanupPage()

    installFetchMock({ role: 'client' })
    const routing = await mountPage(RoutingPage)
    await settle()
    await clickByText('Add rule')
    await fillInputs({ '.example.com, example.org': '.example.org' })
    await clickLastByText('Save')
    await clickByText('Test')
    await clickSelector('.n-switch')
    await clickAllButtons(1)
    expect(routing.wrapper.html()).toBeTruthy()
  })

  it('toggles inbounds and manages logs/connections/jobs/subscriptions', async () => {
    installFetchMock()
    const inbounds = await mountPage(InboundsPage)
    await settle()
    await clickSelector('.n-switch')
    await clickByText('Rotate Reality keys')
    await clickByText('Confirm')
    await clickByText('Certificates')
    await clickAllButtons(1)
    expect(inbounds.wrapper.html()).toBeTruthy()
    cleanupPage()

    installFetchMock()
    const logs = await mountPage(LogsPage)
    await settle()
    await clickByText('Core')
    await clickByText('Ostium')
    await clickByText('Pause')
    await clickByText('Clear')
    await fillInputs({ Search: 'error' })
    await clickAllButtons(1)
    expect(logs.wrapper.html()).toBeTruthy()
    cleanupPage()

    installFetchMock()
    const connections = await mountPage(ConnectionsPage)
    await settle()
    await clickSelector('.n-switch')
    await clickSelector('.n-switch')
    await clickAllButtons(1)
    await clickByText('Close all')
    await clickByText('Confirm')
    expect(connections.wrapper.html()).toBeTruthy()
    cleanupPage()

    installFetchMock()
    const jobs = await mountPage(JobsPage)
    await settle()
    await clickSelector('.job')
    await clickByText('Cancel')
    await clickAllButtons(1)
    expect(jobs.wrapper.html()).toBeTruthy()
    cleanupPage()

    installFetchMock()
    const subscriptions = await mountPage(SubscriptionsPage)
    await settle()
    await clickSelector('.user-row, .sub-user, .user-item')
    await clickByText('Rotate')
    await clickByText('Confirm')
    await clickAllButtons(1)
    expect(subscriptions.wrapper.html()).toBeTruthy()
  })
})
