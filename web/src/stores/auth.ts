import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api'
import type { AuthStatus, Me } from '@/api/types'

export const useAuthStore = defineStore('auth', () => {
  const status = ref<AuthStatus | null>(null)
  const me = ref<Me | null>(null)
  const loading = ref(false)
  const ready = ref(false)
  const error = ref<string | null>(null)

  const initialized = computed(() => status.value?.initialized ?? false)
  const authenticated = computed(() => status.value?.authenticated ?? false)
  const role = computed(() => status.value?.role ?? 'server')
  const isServer = computed(() => role.value === 'server')
  const isClient = computed(() => role.value === 'client')
  const mustChangePassword = computed(() => me.value?.must_change_password ?? false)
  const totpEnabled = computed(() => me.value?.totp_enabled ?? false)

  async function bootstrap() {
    if (ready.value) return
    loading.value = true
    try {
      status.value = await api.auth.status()
      if (status.value.authenticated) {
        me.value = await api.auth.me()
      } else {
        me.value = null
      }
      error.value = null
    } catch (err) {
      error.value = (err as Error).message
    } finally {
      loading.value = false
      ready.value = true
    }
  }

  async function refresh() {
    status.value = await api.auth.status()
    me.value = status.value.authenticated ? await api.auth.me() : null
  }

  async function login(username: string, password: string, totp?: string, recoveryCode?: string) {
    await api.auth.login(username, password, totp, recoveryCode)
    await refresh()
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
    await refresh()
  }

  async function logout() {
    try {
      await api.auth.logout()
    } finally {
      status.value = status.value ? { ...status.value, authenticated: false } : null
      me.value = null
    }
  }

  function expire() {
    // A 401 from any API must update the guard's source of truth before it
    // redirects to /login; otherwise the guard sees the stale authenticated
    // flag and immediately sends the user back to the protected page.
    status.value = status.value ? { ...status.value, authenticated: false } : null
    me.value = null
  }

  return {
    status,
    me,
    loading,
    ready,
    error,
    initialized,
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
