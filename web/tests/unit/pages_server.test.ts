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
