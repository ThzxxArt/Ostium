import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api'
import type { AuthStatus, Me } from '@/api/types'
import { useAppStore } from './app'
import { useEventStore } from './events'

export type AuthState = 'idle' | 'ready' | 'error'

export const useAuthStore = defineStore('auth', () => {
  const status = ref<AuthStatus | null>(null)
  const me = ref<Me | null>(null)
  const loading = ref(false)
  const ready = ref(false)
  const error = ref<string | null>(null)
  const statusState = ref<AuthState>('idle')
  let inFlight: Promise<void> | null = null

  const initialized = computed(() => status.value?.initialized === true)
  const hasAdmin = computed(() => status.value?.has_admin === true)
  const authenticated = computed(() => status.value?.authenticated ?? false)
  const role = computed(() => status.value?.role ?? 'server')
  const isServer = computed(() => role.value === 'server')
  const isClient = computed(() => role.value === 'client')
  const mustChangePassword = computed(() => me.value?.must_change_password ?? false)
  const totpEnabled = computed(() => me.value?.totp_enabled ?? false)

  async function load(force: boolean): Promise<void> {
    if (!force && ready.value && statusState.value !== 'error') return
    if (inFlight) return inFlight
    loading.value = true
    inFlight = (async () => {
      try {
        status.value = await api.auth.status()
        me.value = status.value.authenticated ? await api.auth.me() : null
        error.value = null
        statusState.value = 'ready'
      } catch (err) {
        // A failed status probe must never be interpreted as "not initialized":
        // that sent existing installations to /setup and locked the operator
        // out even though the administrator still existed.
        error.value = err instanceof Error ? err.message : String(err)
        statusState.value = 'error'
      } finally {
        loading.value = false
        ready.value = true
        inFlight = null
      }
    })()
    return inFlight
  }

  async function bootstrap(force = false) {
    await load(force)
  }

  async function refresh() {
    await load(true)
    if (statusState.value === 'error') {
      throw new Error(error.value ?? 'authentication status is unavailable')
    }
  }

  function markAuthenticatedAfterRefreshFailure() {
    // The login/setup API call already succeeded and set the session cookie.
    // If the follow-up status request fails, keep the successful fact instead
    // of showing "login failed" and leaving the user on the form.
    status.value = {
      initialized: true,
      has_admin: true,
      authenticated: true,
      must_change_password: false,
      totp_enabled: status.value?.totp_enabled ?? false,
      role: status.value?.role ?? 'server',
      version: status.value?.version ?? '',
      public_ui: status.value?.public_ui ?? false,
    }
    me.value = null
    statusState.value = 'ready'
  }

  async function login(username: string, password: string, totp?: string, recoveryCode?: string) {
    await api.auth.login(username, password, totp, recoveryCode)
    try {
      await refresh()
    } catch {
      markAuthenticatedAfterRefreshFailure()
    }
  }

  async function setup(payload: {
    role: string
    username: string
    password: string
    domain?: string
    public_ui?: boolean
    lines?: 'reality' | 'later'
  }) {
    await api.auth.setup(payload)
    try {
      await refresh()
    } catch {
      markAuthenticatedAfterRefreshFailure()
    }
  }

  function clearSessionCaches(): void {
    // Components outside RouterView (palette, job drawer) survive the logout
    // navigation.  Leaving their data in place shows the previous account's
    // users and jobs to the next person at the browser.
    const app = useAppStore()
    const events = useEventStore()
    app.jobDrawerOpen = false
    app.commandOpen = false
    app.mobileNavOpen = false
    events.reset()
  }

  async function logout() {
    try {
      await api.auth.logout()
    } finally {
      status.value = status.value ? { ...status.value, authenticated: false } : null
      me.value = null
      clearSessionCaches()
    }
  }

  function expire() {
    // A 401 from any API must update the guard's source of truth before it
    // redirects to /login; otherwise the guard sees the stale authenticated
    // flag and immediately sends the user back to the protected page.
    status.value = status.value ? { ...status.value, authenticated: false } : null
    me.value = null
    clearSessionCaches()
  }

  return {
    status,
    me,
    loading,
    ready,
    error,
    statusState,
    initialized,
    hasAdmin,
    authenticated,
    role,
    isServer,
    isClient,
    mustChangePassword,
    totpEnabled,
    bootstrap,
    refresh,
    login,
    setup,
    logout,
    expire,
  }
})
