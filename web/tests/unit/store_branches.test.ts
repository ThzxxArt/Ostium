import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { useEventStore } from '@/stores/events'
import { installFetchMock } from './helpers'
import { i18n } from '@/locales'
import {
  formatDate,
  formatDay,
  formatDuration,
  formatPercent,
  relativeTime,
  statusTone,
} from '@/utils/format'

describe('store and utility branches', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.unstubAllGlobals()
    setActivePinia(createPinia())
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('short-circuits auth bootstrap and refresh when unauthenticated', async () => {
    const store = useAuthStore()
    store.ready = true
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await store.bootstrap()
    expect(fetchMock).not.toHaveBeenCalled()

    store.ready = false
    installFetchMock({
      overrides: {
        '/api/v1/auth/status': {
          initialized: true,
          has_admin: true,
          authenticated: false,
          must_change_password: true,
          totp_enabled: false,
          role: 'server',
          version: '0.1.0',
          public_ui: false,
        },
      },
    })
    await store.bootstrap()
    expect(store.authenticated).toBe(false)
    expect(store.me).toBeNull()
    await store.refresh()
    expect(store.me).toBeNull()
  })

  it('logout clears state even when the API fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new Error('offline'))),
    )
    const store = useAuthStore()
    store.status = {
      initialized: true,
      has_admin: true,
      authenticated: true,
      must_change_password: false,
      totp_enabled: false,
      role: 'server',
      version: '0.1.0',
      public_ui: false,
    }
    store.me = {
      id: '1',
      username: 'admin',
      must_change_password: false,
      totp_enabled: false,
      recovery_codes_remaining: 0,
      last_login_at: null,
      role: 'server',
    }
    await expect(store.logout()).rejects.toThrow()
    expect(store.me).toBeNull()
    expect(store.status?.authenticated).toBe(false)
    expect(store.mustChangePassword).toBe(false)
    expect(store.totpEnabled).toBe(false)
  })

  it('reacts to system theme changes', () => {
    let listener: any = null
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn(() => ({
        matches: false,
        addEventListener: (_: string, cb: (event: { matches: boolean }) => void) => {
          listener = cb
        },
      })),
    })
    localStorage.setItem('ostium.theme', 'system')
    const store = useAppStore()
    expect(store.isDark).toBe(false)
    listener?.({ matches: true })
    expect(store.isDark).toBe(true)
    listener?.({ matches: false })
    expect(store.isDark).toBe(false)
    store.setTheme('light')
    listener?.({ matches: true })
    expect(store.isDark).toBe(false)
  })

  it('schedules one retry and tolerates constructor failures', () => {
    vi.useFakeTimers()
    const store = useEventStore()
    let attempts = 0
    vi.stubGlobal(
      'WebSocket',
      class {
        constructor() {
          attempts += 1
          throw new Error('blocked')
        }
      },
    )
    store.connect()
    store.connect()
    vi.advanceTimersByTime(1000)
    expect(attempts).toBeGreaterThanOrEqual(2)
    store.disconnect()
  })

  it('formats calendar-only days without a timezone shift', () => {
    const original = process.env.TZ
    process.env.TZ = 'America/New_York'
    try {
      expect(formatDay('2026-01-01', 'en-US')).toBe('Jan 1')
    } finally {
      process.env.TZ = original
    }
  })

  it('formats edge-case dates and statuses', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate('not-a-date')).toBe('—')
    expect(formatDate('2026-01-01T00:00:00Z', 'en-US')).toBeTruthy()
    expect(formatDay('2026-01-01')).toBeTruthy()
    expect(relativeTime(null)).toBe('—')
    expect(relativeTime('not-a-date')).toBe('—')
    expect(relativeTime('2026-01-01T00:00:00Z', 'en-US')).toBeTruthy()
    expect(formatDuration(59)).toBe('59s')
    expect(formatDuration(3600)).toBe('1h 0m')
    expect(formatPercent(12.6)).toBe('13%')
    expect(statusTone('pending')).toBe('warning')
    expect(statusTone('interrupted')).toBe('danger')
    expect(statusTone('offline')).toBe('neutral')
    expect(statusTone('something-else')).toBe('info')
    expect(i18n.global.locale.value).toBeTruthy()
  })
})
