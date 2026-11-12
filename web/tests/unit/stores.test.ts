import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { useEventStore } from '@/stores/events'
import { currentLocale, i18n, setLocale } from '@/locales'
import { installFetchMock } from './helpers'

class FakeSocket {
  static instances: FakeSocket[] = []
  listeners = new Map<string, Array<(event: any) => void>>()
  closed = false

  constructor(public url: string) {
    FakeSocket.instances.push(this)
  }

  addEventListener(type: string, listener: (event: any) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) || []), listener])
  }

  emit(type: string, event: any = {}) {
    for (const listener of this.listeners.get(type) || []) listener(event)
  }

  close() {
    this.closed = true
    this.emit('close')
  }
}

describe('stores', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    FakeSocket.instances = []
  })

  it('bootstraps, refreshes, logs in and out', async () => {
    installFetchMock()
    const store = useAuthStore()
    await store.bootstrap()
    expect(store.initialized).toBe(true)
    expect(store.authenticated).toBe(true)
    expect(store.me?.username).toBe('admin')
    expect(store.role).toBe('server')
    expect(store.isServer).toBe(true)
    expect(store.isClient).toBe(false)

    await store.bootstrap()
    expect(store.loading).toBe(false)

    await store.refresh()
    expect(store.authenticated).toBe(true)

    await store.login('admin', 'secret')
    expect(store.authenticated).toBe(true)

    await store.setup({ role: 'server', username: 'admin', password: 'secret' })
    expect(store.authenticated).toBe(true)

    await store.logout()
    expect(store.me).toBeNull()
    expect(store.status?.authenticated).toBe(false)
  })

  it('captures bootstrap errors and handles missing status', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 500,
        headers: new Headers({ 'content-type': 'application/problem+json' }),
        json: async () => ({ detail: 'nope' }),
        text: async () => 'nope',
      })),
    )
    const store = useAuthStore()
    await store.bootstrap()
    expect(store.error).toBeTruthy()
    expect(store.ready).toBe(true)

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ ok: true }),
        text: async () => '{}',
      })),
    )
    store.status = null
    await store.logout()
    expect(store.status).toBeNull()
  })

  it('applies themes, language and sidebar state', () => {
    localStorage.setItem('ostium.theme', 'system')
    localStorage.setItem('ostium.sidebar', 'collapsed')
    const store = useAppStore()
    expect(store.theme).toBe('system')
    expect(store.isDark).toBe(false)

    store.restoreSidebar()
    expect(store.sidebarCollapsed).toBe(true)

    store.setTheme('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('ostium.theme')).toBe('light')

    store.toggleTheme()
    expect(store.theme).toBe('dark')
    expect(store.isDark).toBe(true)

    store.toggleLanguage()
    expect(store.locale).toBe('zh-CN')
    expect(currentLocale()).toBe('zh-CN')
    store.toggleLanguage()
    expect(store.locale).toBe('en-US')

    const before = store.sidebarCollapsed
    store.toggleSidebar()
    expect(store.sidebarCollapsed).toBe(!before)
  })

  it('ignores storage failures and invalid themes', () => {
    localStorage.setItem('ostium.theme', 'invalid')
    const store = useAppStore()
    expect(store.theme).toBe('dark')

    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota')
    })
    expect(() => store.setTheme('light')).not.toThrow()
    expect(() => store.toggleSidebar()).not.toThrow()
    setItem.mockRestore()

    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(() => store.restoreSidebar()).not.toThrow()
    getItem.mockRestore()

    const setLocaleSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(() => setLocale('zh-CN')).not.toThrow()
    setLocaleSpy.mockRestore()
    setLocale('en-US')
    expect(i18n.global.locale.value).toBe('en-US')
  })

  it('connects the event socket and handles frames', () => {
    vi.useFakeTimers()
    vi.stubGlobal('WebSocket', FakeSocket)
    const store = useEventStore()

    store.connect()
    const socket = FakeSocket.instances[0]
    expect(socket.url).toContain('/api/v1/events')
    socket.emit('open')
    expect(store.connected).toBe(true)

    socket.emit('message', { data: JSON.stringify({ type: 'ping', data: {} }) })
    expect(store.frames).toHaveLength(0)

    socket.emit('message', { data: '{invalid' })
    expect(store.frames).toHaveLength(0)

    socket.emit('message', {
      data: JSON.stringify({ type: 'log', ts: 'now', data: { message: 'hi' } }),
    })
    socket.emit('message', {
      data: JSON.stringify({ type: 'job.updated', ts: 'now', data: { id: 'job-1' } }),
    })
    socket.emit('message', {
      data: JSON.stringify({ type: 'alert.created', ts: 'now', data: { id: 'alert-1' } }),
    })
    socket.emit('message', {
      data: JSON.stringify({ type: 'engine.applied', ts: 'now', data: {} }),
    })
    socket.emit('message', {
      data: JSON.stringify({ type: 'stats.tick', ts: 'now', data: {} }),
    })
    expect(store.lastLog?.type).toBe('log')
    expect(store.lastJob?.type).toBe('job.updated')
    expect(store.lastAlert?.type).toBe('alert.created')
    expect(store.lastEngine?.type).toBe('stats.tick')

    for (let index = 0; index < 210; index += 1) {
      socket.emit('message', {
        data: JSON.stringify({ type: 'other', ts: 'now', data: { index } }),
      })
    }
    expect(store.frames).toHaveLength(200)

    socket.emit('error')
    expect(socket.closed).toBe(true)

    store.disconnect()
    expect(store.connected).toBe(false)
    vi.useRealTimers()
  })

  it('schedules reconnects after a close and catches constructor errors', () => {
    vi.useFakeTimers()
    const store = useEventStore()
    vi.stubGlobal(
      'WebSocket',
      class {
        constructor() {
          throw new Error('unavailable')
        }
      },
    )
    store.connect()
    vi.advanceTimersByTime(1000)
    store.disconnect()

    vi.stubGlobal('WebSocket', FakeSocket)
    store.connect()
    const socket = FakeSocket.instances[0]
    socket.emit('open')
    socket.emit('close')
    expect(store.connected).toBe(false)
    expect(FakeSocket.instances).toHaveLength(1)

    vi.advanceTimersByTime(1000)
    expect(FakeSocket.instances).toHaveLength(2)
    vi.useRealTimers()
    store.disconnect()
  })
})
