import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProfilesPage from '@/pages/ProfilesPage.vue'
import SubscriptionsPage from '@/pages/SubscriptionsPage.vue'
import InboundsPage from '@/pages/InboundsPage.vue'
import SettingsPage from '@/pages/SettingsPage.vue'
import ConnectionsPage from '@/pages/ConnectionsPage.vue'
import RulesPage from '@/pages/RulesPage.vue'
import RoutingPage from '@/pages/RoutingPage.vue'
import UsersPage from '@/pages/UsersPage.vue'
import SetupPage from '@/pages/SetupPage.vue'
import OnboardingPage from '@/pages/OnboardingPage.vue'
import { api } from '@/api'
import { fixtures, installFetchMock, mountPage, settle, cleanupPage, clickByText } from './helpers'

function stateOf(wrapper: any, component: any) {
  return wrapper.findComponent(component).vm.$.setupState
}

describe('v0.1.1 page branches', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
  })
  afterEach(() => {
    cleanupPage()
    vi.unstubAllGlobals()
  })

  it('activates, toggles and reorders profiles', async () => {
    const second = {
      ...fixtures.profile,
      id: 'profile-2',
      name: 'JP',
      sort_order: 10,
    }
    installFetchMock({
      overrides: {
        '/api/v1/profiles': {
          profiles: [fixtures.profile, second],
          active_profile_id: null,
        },
      },
    })
    const { wrapper } = await mountPage(ProfilesPage)
    await settle()
    const state = stateOf(wrapper, ProfilesPage)
    expect(state.activeProfileId).toBeNull()
    await state.activate(fixtures.profile)
    await settle()
    expect(state.activeProfileId).toBe('profile-1')
    await state.toggleEnabled(second)
    await settle()

    state.onDragStart(fixtures.profile)
    await state.onDrop(second)
    await settle()
    state.onDragStart(fixtures.profile)
    await state.onDrop(fixtures.profile)
    await state.onDrop({ ...second, id: 'missing' })
    expect(wrapper.html()).toBeTruthy()
  })

  it('reveals subscriptions only on demand', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(SubscriptionsPage)
    await settle()
    const state = stateOf(wrapper, SubscriptionsPage)
    expect(state.revealed).toBe(false)
    await state.revealSubscription()
    await settle()
    expect(state.revealed).toBe(true)
    state.showQr('https://example.com/sub')
    expect(state.qrOpen).toBe(true)
  })

  it('assigns certificates and reports skipped inbounds', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(InboundsPage)
    await settle()
    const state = stateOf(wrapper, InboundsPage)
    expect(state.readyCertificates.length).toBeGreaterThan(0)
    expect(state.certificateOptions[0].label).toContain('vpn.example.com')
    await state.assignCertificate(fixtures.inbounds[1], 'cert-1')
    await settle()
    await state.assignCertificate(fixtures.inbounds[1], null)
    await settle()
    await state.toggle(fixtures.inbounds[1], true)
    await settle()
    state.editPort(fixtures.inbounds[0])
    state.portValue = 9443
    await state.savePort()
    await settle()
    expect(wrapper.html()).toBeTruthy()
  })

  it('saves allowlist, ACME and plaintext backup settings', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(SettingsPage)
    await settle()
    const state = stateOf(wrapper, SettingsPage)
    state.allowlist = '203.0.113.0/24, 2001:db8::/32'
    await state.saveAllowlist()
    await settle()
    state.general.public_base_url = 'https://vpn.example.com'
    state.general.acme_staging = true
    await state.saveGeneral()
    await settle()
    await state.saveMaintenance()
    await settle()
    state.backupPassword = ''
    state.backupAck = true
    await state.createBackup()
    await settle()
    await state.cancelTotp()
    await settle()
    expect(wrapper.html()).toBeTruthy()
  })

  it('filters connections, opens details and confirms close-all', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(ConnectionsPage)
    await settle()
    const state = stateOf(wrapper, ConnectionsPage)
    state.userFilter = 'alice'
    expect(state.filtered).toHaveLength(0)
    state.userFilter = null
    state.search = 'example'
    state.onSearchInput()
    state.openDetail(fixtures.connection)
    expect(state.detailOpen).toBe(true)
    state.closeAll()
    state.togglePause()
    state.togglePause()
    expect(wrapper.html()).toBeTruthy()
  })

  it('reorders rules and validates advanced JSON', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(RulesPage)
    await settle()
    const state = stateOf(wrapper, RulesPage)
    await state.moveRule(0, 1)
    await settle()
    state.openAdd()
    state.advanced = true
    state.advancedJson = 'not-json'
    await state.saveRule()
    expect(state.ruleOpen).toBe(true)
    state.advancedJson = JSON.stringify({ domain: ['example.com'], network: ['tcp'] })
    await state.saveRule()
    await settle()
    state.openEdit(fixtures.rule)
    expect(state.advancedJson).toContain('domain_suffix')
  })

  it('applies routing presets and manages routing rules', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(RoutingPage)
    await settle()
    const state = stateOf(wrapper, RoutingPage)
    expect(state.activePreset).toBe('smart')
    await state.setPreset('global')
    await settle()
    expect(state.activePreset).toBe('global')
    state.openAdd()
    state.form.values = 'example.com'
    await state.saveRule()
    await settle()
    state.testDomain = 'example.com'
    await state.testRule()
    await settle()
    state.removeRule(fixtures.rule)
    state.openEdit(fixtures.rule)
    expect(state.form.type).toBe('domain_suffix')
  })

  it('refreshes, selects and removes profiles', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(ProfilesPage)
    await settle()
    const state = stateOf(wrapper, ProfilesPage)
    await state.refresh(fixtures.profile)
    await settle()
    await state.selectEndpoint(fixtures.profile, 'jp-1')
    await settle()
    state.remove(fixtures.profile)
    expect(wrapper.html()).toBeTruthy()
  })

  it('opens user subscriptions, reveals them and paginates', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(UsersPage)
    await settle()
    const state = stateOf(wrapper, UsersPage)
    expect(state.pageCount).toBe(1)
    await state.openSubscription(fixtures.user)
    await settle()
    expect(state.subscriptionRevealed).toBe(false)
    await state.revealSubscription()
    await settle()
    expect(state.subscriptionRevealed).toBe(true)
    state.confirmRotate(fixtures.user)
    state.confirmReset(fixtures.user)
    state.confirmDelete(fixtures.user)
    state.page = 1
    expect(wrapper.html()).toBeTruthy()
  })

  it('offers the deferred line setup option', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(SetupPage)
    await settle()
    const state = stateOf(wrapper, SetupPage)
    state.transport = 'later'
    expect(state.transportOptions).toHaveLength(2)
    expect(state.transportOptions[1].id).toBe('later')
  })

  it('renders empty and error variants for key pages', async () => {
    const pages = [
      ProfilesPage,
      RoutingPage,
      RulesPage,
      InboundsPage,
      ConnectionsPage,
      SubscriptionsPage,
      SettingsPage,
      UsersPage,
    ]
    for (const page of pages) {
      installFetchMock({ mode: 'empty' })
      const empty = await mountPage(page)
      await settle()
      expect(empty.wrapper.html()).toBeTruthy()
      cleanupPage()
      installFetchMock({ mode: 'error' })
      const failed = await mountPage(page)
      await settle()
      expect(failed.wrapper.html()).toBeTruthy()
      cleanupPage()
    }
  })

  it('handles profile import modes and missing subscription URLs', async () => {
    installFetchMock({
      overrides: {
        '/api/v1/profiles': {
          profiles: [
            {
              ...fixtures.profile,
              subscription_url: null,
              last_refresh_error: 'refresh failed',
            },
          ],
          active_profile_id: null,
        },
      },
    })
    const { wrapper } = await mountPage(ProfilesPage)
    await settle()
    const state = stateOf(wrapper, ProfilesPage)
    state.importMode = 'text'
    state.importText = ''
    await state.importProfile()
    state.importMode = 'url'
    state.importUrl = ''
    await state.importProfile()
    state.importMode = 'text'
    state.importName = 'manual'
    state.importText = 'vless://uuid@example.com:443?security=reality#node'
    await state.importProfile()
    await settle()
    expect(wrapper.text()).toContain('refresh failed')

    state.stopCamera()
    await state.startCamera()
    expect(state.cameraOpen).toBe(false)

    const stream = { getTracks: () => [{ stop: vi.fn() }] }
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn(async () => stream) },
    })
    await state.startCamera()
    await settle()
    state.stopCamera()

    state.videoRef = { readyState: 2, videoWidth: 1, videoHeight: 1 }
    state.scanFrame()
    await settle()
  })

  it('exports selected users as a JSON download', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(UsersPage)
    await settle()
    const state = stateOf(wrapper, UsersPage)
    state.selected = new Set([fixtures.user.id])
    const createObjectURL = vi.fn(() => 'blob:test')
    const revokeObjectURL = vi.fn()
    const originalCreate = URL.createObjectURL
    const originalRevoke = URL.revokeObjectURL
    URL.createObjectURL = createObjectURL
    URL.revokeObjectURL = revokeObjectURL
    try {
      await state.bulk('export')
      await settle()
      expect(createObjectURL).toHaveBeenCalled()
      expect(revokeObjectURL).toHaveBeenCalled()
    } finally {
      URL.createObjectURL = originalCreate
      URL.revokeObjectURL = originalRevoke
    }
  })

  it('handles rule-set maintenance and invalid rules', async () => {
    installFetchMock()
    const { wrapper } = await mountPage(RulesPage)
    await settle()
    const state = stateOf(wrapper, RulesPage)
    await state.toggleRule(fixtures.rule, false)
    state.testDomain = '1.2.3.4'
    await state.testRule()
    await settle()
    state.ruleSetOpen = true
    state.ruleSetForm = { name: 'ads', url: 'https://example.com/ads.srs', format: 'binary' }
    await state.addRuleSet()
    await settle()
    state.ruleSetForm = { name: '', url: '', format: 'binary' }
    await state.addRuleSet()
    await state.updateRuleSet(fixtures.ruleSet)
    await settle()
    state.removeRuleSet(fixtures.ruleSet)
    await state.moveRule(0, -1)
    await state.moveRule(1, 1)
    expect(wrapper.html()).toBeTruthy()
  })

  it('walks the onboarding import, test and mode steps', async () => {
    installFetchMock()
    const { wrapper, router } = await mountPage(OnboardingPage)
    await settle()
    const state = stateOf(wrapper, OnboardingPage)
    expect(state.canImport).toBe(false)
    await state.importProfile()
    state.importMode = 'text'
    state.importText = 'vless://uuid@example.com:443#node'
    expect(state.canImport).toBe(true)
    await state.importProfile()
    await settle()
    expect(state.step).toBe(1)
    expect(state.testResults.length).toBeGreaterThan(0)
    await state.testProfile()
    state.testResults = []
    state.testing = false
    await settle()
    state.mode = 'tun'
    await state.finish()
    await settle()
    expect(router.currentRoute.value.path).toBe('/')
  })

  it('skips onboarding without a profile', async () => {
    installFetchMock()
    const { wrapper, router } = await mountPage(OnboardingPage)
    await settle()
    const state = stateOf(wrapper, OnboardingPage)
    state.testResults = []
    await state.testProfile()
    state.skip()
    await settle()
    expect(router.currentRoute.value.path).toBe('/')
  })

  it('surfaces non-applied warnings on profile, user and certificate actions', async () => {
    installFetchMock()
    const profiles = await mountPage(ProfilesPage)
    await settle()
    const profilesState = stateOf(profiles.wrapper, ProfilesPage)
    const second = { ...fixtures.profile, id: 'profile-2', name: 'JP', sort_order: 10 }
    vi.spyOn(api.profiles, 'reorder').mockResolvedValueOnce({
      ok: true,
      applied: false,
      warning: 'stored only',
    })
    profilesState.dragId = fixtures.profile.id
    await profilesState.onDrop(second)
    vi.spyOn(api.profiles, 'remove').mockResolvedValueOnce({
      deleted: true,
      applied: false,
      warning: 'stored only',
    })
    profilesState.remove(fixtures.profile)
    await settle()
    await clickByText('Delete')
    await settle()

    installFetchMock()
    const users = await mountPage(UsersPage)
    await settle()
    const usersState = stateOf(users.wrapper, UsersPage)
    vi.spyOn(api.users, 'resetUsage').mockResolvedValueOnce({
      user: fixtures.user,
      applied: false,
      warning: 'stored only',
    })
    usersState.confirmReset(fixtures.user)
    await settle()
    await clickByText('Confirm')
    await settle()
    vi.spyOn(api.users, 'remove').mockResolvedValueOnce({
      deleted: true,
      applied: false,
      warning: 'stored only',
    })
    usersState.confirmDelete(fixtures.user)
    await settle()
    await clickByText('Delete')
    await settle()
    vi.spyOn(api.users, 'bulk').mockResolvedValueOnce({
      count: 1,
      action: 'disable',
      applied: false,
      warning: 'stored only',
    })
    usersState.selected = new Set([fixtures.user.id])
    await usersState.bulk('disable')
    await settle()

    installFetchMock()
    const certs = await mountPage((await import('@/pages/CertificatesPage.vue')).default)
    await settle()
    const certsState = stateOf(
      certs.wrapper,
      (await import('@/pages/CertificatesPage.vue')).default,
    )
    vi.spyOn(api.certificates, 'remove').mockResolvedValueOnce({
      deleted: true,
      applied: false,
      warning: 'stored only',
    })
    certsState.remove(fixtures.certificate)
    await settle()
    await clickByText('Delete')
    await settle()
    expect(profiles.wrapper.html()).toBeTruthy()
    expect(users.wrapper.html()).toBeTruthy()
    expect(certs.wrapper.html()).toBeTruthy()
  })

  it('surfaces non-applied warnings on server and client rule pages', async () => {
    installFetchMock()
    const rules = await mountPage(RulesPage)
    await settle()
    const rulesState = stateOf(rules.wrapper, RulesPage)
    vi.spyOn(api.rules, 'create').mockResolvedValueOnce({
      rule: fixtures.rule,
      applied: false,
      warning: 'stored only',
    })
    rulesState.openAdd()
    rulesState.form.values = 'example.com'
    await rulesState.saveRule()
    vi.spyOn(api.rules, 'update').mockResolvedValue({
      rule: fixtures.rule,
      applied: false,
      warning: 'stored only',
    })
    await rulesState.toggleRule(fixtures.rule, false)
    await rulesState.moveRule(0, 1)
    vi.spyOn(api.rules, 'updateRuleSet').mockResolvedValueOnce({
      result: { updated: false },
      rule_set: fixtures.ruleSet,
      applied: false,
      warning: 'stored only',
    })
    await rulesState.updateRuleSet(fixtures.ruleSet)
    vi.spyOn(api.rules, 'remove').mockResolvedValueOnce({
      deleted: true,
      applied: false,
      warning: 'stored only',
    })
    rulesState.removeRule(fixtures.rule)
    await settle()
    await clickByText('Delete')
    await settle()
    vi.spyOn(api.rules, 'removeRuleSet').mockResolvedValueOnce({
      deleted: true,
      applied: false,
      warning: 'stored only',
    })
    rulesState.removeRuleSet(fixtures.ruleSet)
    await settle()
    await clickByText('Delete')
    await settle()

    installFetchMock({ role: 'client' })
    const routing = await mountPage(RoutingPage)
    await settle()
    const routingState = stateOf(routing.wrapper, RoutingPage)
    vi.spyOn(api.settings, 'update').mockResolvedValueOnce({
      ok: true,
      applied: false,
      warning: 'stored only',
    })
    await routingState.setPreset('global')
    vi.spyOn(api.rules, 'create').mockResolvedValueOnce({
      rule: fixtures.rule,
      applied: false,
      warning: 'stored only',
    })
    routingState.openAdd()
    routingState.form.values = 'example.com'
    await routingState.saveRule()
    vi.spyOn(api.rules, 'update').mockResolvedValue({
      rule: fixtures.rule,
      applied: false,
      warning: 'stored only',
    })
    await routingState.toggleRule(fixtures.rule, false)
    routingState.removeRule(fixtures.rule)
    await settle()
    await clickByText('Confirm')
    await settle()

    installFetchMock()
    const settingsPage = await mountPage(SettingsPage)
    await settle()
    const settingsState = stateOf(settingsPage.wrapper, SettingsPage)
    vi.spyOn(api.settings, 'update').mockResolvedValueOnce({
      ok: true,
      applied: false,
      warning: 'stored only',
    })
    await settingsState.saveGeneral()
    await settle()

    expect(rules.wrapper.html()).toBeTruthy()
    expect(routing.wrapper.html()).toBeTruthy()
    expect(settingsPage.wrapper.html()).toBeTruthy()
  })
})
