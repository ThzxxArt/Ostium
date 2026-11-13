import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import UsersPage from '@/pages/UsersPage.vue'
import RulesPage from '@/pages/RulesPage.vue'
import RoutingPage from '@/pages/RoutingPage.vue'
import ProfilesPage from '@/pages/ProfilesPage.vue'
import LogsPage from '@/pages/LogsPage.vue'
import CertificatesPage from '@/pages/CertificatesPage.vue'
import ConnectionsPage from '@/pages/ConnectionsPage.vue'
import SettingsPage from '@/pages/SettingsPage.vue'
import { useAuthStore } from '@/stores/auth'
import { fixtures, installFetchMock, mountPage, settle, cleanupPage } from './helpers'

function stateOf(wrapper: any, component: any) {
  return wrapper.findComponent(component).vm.$.setupState
}

describe('page script branches', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
    vi.stubGlobal(
      'prompt',
      vi.fn(() => 'password123'),
    )
  })
  afterEach(() => {
    cleanupPage()
    vi.unstubAllGlobals()
  })

  it('exercises user filters, parsing and row actions', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(UsersPage)
    const state = stateOf(wrapper, UsersPage)
    await settle()

    state.search = 'alice'
    expect(state.filtered).toHaveLength(1)
    state.search = ''
    state.filter = 'online'
    expect(state.filtered).toHaveLength(1)
    state.filter = 'disabled'
    expect(state.filtered).toHaveLength(1)
    state.filter = 'expired'
    expect(state.filtered).toHaveLength(0)
    state.filter = 'quota_exceeded'
    expect(state.filtered).toHaveLength(0)
    state.filter = 'all'
    expect(state.filtered).toHaveLength(2)

    expect(state.parseBytes('')).toBe(0)
    expect(state.parseBytes('1.5G')).toBe(Math.round(1.5 * 1024 ** 3))
    expect(Number.isNaN(state.parseBytes('nope'))).toBe(true)
    expect(state.parseBytes('2M')).toBe(2 * 1024 ** 2)
    expect(state.parseBytes('3KB')).toBe(3 * 1024)
    expect(state.parseBytes('4TIB')).toBe(4 * 1024 ** 4)

    for (const status of ['expired', 'quota_exceeded', 'active']) {
      const user = { ...fixtures.user, online: false, status }
      expect(state.statusLabel(user)).toBeTruthy()
    }
    expect(state.statusLabel({ ...fixtures.disabledUser, disabled_reason: null })).toBeTruthy()

    state.openCreate()
    expect(state.createOpen).toBe(true)
    state.form.name = ''
    await state.save()
    state.form.name = 'alice'
    state.form.quota = 'bad'
    await state.save()
    state.form.quota = ''
    state.form.expires = Date.now()
    state.form.note = 'note'
    await state.save()

    const user = fixtures.user
    state.openEdit(user)
    expect(state.editing.id).toBe(user.id)
    state.openDetail(user)
    state.openSubscription(user)
    state.showQr('vless://x')
    expect(state.qrOpen).toBe(true)

    state.toggleSelect(user.id)
    expect(state.selected.has(user.id)).toBe(true)
    state.toggleSelect(user.id)
    state.toggleSelectAll()
    expect(state.selected.size).toBeGreaterThan(0)
    state.toggleSelectAll()
    expect(state.selected.size).toBe(0)

    for (const key of ['subscription', 'rotate', 'reset', 'toggle', 'delete', 'unknown']) {
      state.onRowAction(user, key)
    }
    state.confirmRotate(user)
    state.confirmReset(user)
    state.confirmDelete(user)
    await state.bulk('enable')
    state.selected = new Set([user.id])
    await state.bulk('enable')
    await state.bulk('disable')
    await state.bulk('delete')
    expect(state.rowOptions(user).length).toBeGreaterThan(1)
    expect(wrapper.html()).toBeTruthy()
  })

  it('exercises rule testing, editing and rule-set branches', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(RulesPage)
    const state = stateOf(wrapper, RulesPage)
    await settle()

    expect(state.matchSummary(fixtures.rule)).toContain('domain_suffix')
    expect(state.matchSummary({ ...fixtures.rule, match: {} })).toBe('')
    expect(state.actionTone('direct')).toBe('direct')
    expect(state.actionTone('block')).toBe('block')
    expect(state.actionTone('proxy')).toBe('proxy')

    state.openAdd()
    state.form.values = ''
    await state.saveRule()
    state.form.values = '.example.com'
    state.form.note = 'note'
    await state.saveRule()
    state.openEdit(fixtures.rule)
    expect(state.editing.id).toBe(fixtures.rule.id)
    state.form.values = '.example.net'
    await state.saveRule()
    await state.toggleRule(fixtures.rule, false)
    state.removeRule(fixtures.rule)
    state.testDomain = ''
    await state.testRule()
    state.testDomain = '1.2.3.4'
    await state.testRule()
    state.testDomain = 'example.com'
    await state.testRule()

    state.ruleSetForm.name = ''
    state.ruleSetForm.url = ''
    await state.addRuleSet()
    state.ruleSetForm.name = 'ads'
    state.ruleSetForm.url = 'https://example.com/ads.srs'
    await state.addRuleSet()
    await state.updateRuleSet(fixtures.ruleSet)
    state.removeRuleSet(fixtures.ruleSet)
    expect(wrapper.html()).toBeTruthy()
  })

  it('exercises routing presets and rule branches', async () => {
    installFetchMock({ role: 'client' })
    const { wrapper } = await mountPage(RoutingPage)
    const state = stateOf(wrapper, RoutingPage)
    await settle()
    for (const preset of ['smart', 'global', 'direct', 'custom']) {
      await state.setPreset(preset)
    }
    expect(state.activePreset).toBe('custom')
    state.openAdd()
    state.form.values = ''
    await state.saveRule()
    state.form.values = 'example.com, example.org'
    state.form.note = 'note'
    await state.saveRule()
    state.openEdit(fixtures.rule)
    state.form.values = '.example.net'
    await state.saveRule()
    await state.toggleRule(fixtures.rule, false)
    state.removeRule(fixtures.rule)
    state.testDomain = ''
    await state.testRule()
    state.testDomain = '1.2.3.4'
    await state.testRule()
    state.testDomain = 'example.com'
    await state.testRule()
    expect(state.matchSummary(fixtures.rule)).toContain('domain')
    expect(state.actionTone('block')).toBe('block')
    expect(wrapper.html()).toBeTruthy()
  })

  it('exercises profile import modes and actions', async () => {
    installFetchMock({ role: 'client' })
    const { wrapper } = await mountPage(ProfilesPage)
    const state = stateOf(wrapper, ProfilesPage)
    await settle()

    state.importMode = 'url'
    state.importUrl = ''
    await state.importProfile()
    state.importUrl = 'https://sub.example.com/hk'
    state.importName = ''
    await state.importProfile()
    state.importMode = 'text'
    state.importText = ''
    await state.importProfile()
    state.importText = 'vless://uuid@example.com:443#HK'
    await state.importProfile()
    await state.refresh(fixtures.profile)
    await state.selectEndpoint(fixtures.profile, 'jp-1')
    state.remove(fixtures.profile)
    state.pickQr()
    await state.onQrFile({ target: { files: [] } } as unknown as Event)
    expect(wrapper.html()).toBeTruthy()
  })

  it('exercises logs filtering, pausing and polling', async () => {
    vi.useFakeTimers()
    installFetchMock()
    const { wrapper } = await mountPage(LogsPage)
    const state = stateOf(wrapper, LogsPage)
    await settle()
    state.level = 'error'
    expect(state.filteredRecords).toHaveLength(1)
    state.search = 'boom'
    expect(state.filteredRecords).toHaveLength(0)
    state.search = 'fail'
    expect(state.filteredRecords).toHaveLength(1)
    state.level = null
    state.search = 'plane'
    expect(state.filteredLines).toHaveLength(1)
    state.appendRecord({ ts: 'now', level: 'info', message: 'appended', context: {} })
    state.togglePause()
    state.appendRecord({ ts: 'now', level: 'info', message: 'paused', context: {} })
    state.source = 'core'
    await settle()
    vi.advanceTimersByTime(2600)
    state.source = 'ostium'
    state.clearView()
    expect(state.records).toHaveLength(0)
    state.follow = true
    await state.scrollToBottom()
    state.follow = false
    await state.load()
    vi.useRealTimers()
    expect(wrapper.html()).toBeTruthy()
  })

  it('exercises certificate status, issue and upload validation', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(CertificatesPage)
    const state = stateOf(wrapper, CertificatesPage)
    await settle()

    expect(state.daysStatus(fixtures.certificate)).toBeTruthy()
    expect(state.daysStatus({ ...fixtures.certificate, days_remaining: 20 })).toBeTruthy()
    expect(state.daysStatus({ ...fixtures.certificate, days_remaining: 5 })).toBeTruthy()
    expect(state.daysStatus({ ...fixtures.certificate, days_remaining: -1 })).toBeTruthy()
    state.issueForm.domain = ''
    await state.issue()
    state.issueForm.domain = 'new.example.com'
    state.issueForm.method = 'self-signed'
    await state.issue()
    state.uploadForm.domain = ''
    state.uploadForm.cert_pem = ''
    state.uploadForm.key_pem = ''
    await state.upload()
    state.uploadForm.domain = 'upload.example.com'
    state.uploadForm.cert_pem = 'cert'
    state.uploadForm.key_pem = 'key'
    await state.upload()
    await state.renew(fixtures.certificate)
    await state.assign(fixtures.certificate)
    state.remove(fixtures.certificate)
    expect(wrapper.html()).toBeTruthy()
  })

  it('exercises connections pause, close and duration', async () => {
    vi.useFakeTimers()
    installFetchMock()
    const { wrapper } = await mountPage(ConnectionsPage)
    const state = stateOf(wrapper, ConnectionsPage)
    await settle()
    expect(state.duration(fixtures.connection)).toBeTruthy()
    state.togglePause()
    state.togglePause()
    await state.closeConnection(fixtures.connection)
    await state.closeAll()
    state.startTimer()
    vi.advanceTimersByTime(3000)
    vi.useRealTimers()
    expect(wrapper.html()).toBeTruthy()
  })

  it('exercises settings validation and backup flows', async () => {
    installFetchMock()
    const { wrapper, pinia } = await mountPage(SettingsPage)
    const state = stateOf(wrapper, SettingsPage)
    const auth = useAuthStore(pinia)
    await settle()

    auth.me = { ...fixtures.me, totp_enabled: false }
    await state.togglePublicUi(true)
    auth.me = { ...fixtures.me, totp_enabled: true }
    state.publicUiDomain = ''
    await state.togglePublicUi(true)
    state.publicUiDomain = 'vpn.example.com'
    await state.togglePublicUi(true)
    await state.togglePublicUi(false)

    state.passwordForm = { current: 'x', next: 'short', confirm: 'short' }
    await state.changePassword()
    state.passwordForm = { current: 'x', next: 'longenough1', confirm: 'different1' }
    await state.changePassword()
    state.passwordForm = { current: 'x', next: 'longenough1', confirm: 'longenough1' }
    await state.changePassword()

    await state.startTotp()
    state.totpCode = '123456'
    await state.confirmTotp()
    await state.disableTotp()
    state.disableTotpPassword = 'verysecret123'
    await state.confirmDisableTotp()

    state.tokenName = ''
    await state.createToken()
    state.tokenName = 'ci'
    await state.createToken()
    state.revokeToken('tok-1')

    await state.createBackup()
    state.restore(fixtures.backup)
    await state.confirmRestore()
    state.removeBackup(fixtures.backup)
    await state.saveGeneral()
    await state.saveNotifications()
    state.clearWebhookSecret = true
    await state.saveNotifications()
    state.clearWebhookSecret = false
    state.notifications.webhook_secret = 'new-secret'
    await state.saveNotifications()
    await state.saveMaintenance()
    state.showQr('https://example.com')
    expect(state.qrOpen).toBe(true)
    expect(wrapper.html()).toBeTruthy()
  })
})
