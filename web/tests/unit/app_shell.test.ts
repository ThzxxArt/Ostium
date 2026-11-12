import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import App from '@/App.vue'
import router from '@/router'
import { i18n } from '@/locales'
import { useAuthStore } from '@/stores/auth'
import { installFetchMock, settle } from './helpers'

let activeWrapper: ReturnType<typeof mount> | null = null

class FakeSocket {
  static instances: FakeSocket[] = []
  listeners = new Map<string, Array<(event: any) => void>>()
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
    this.emit('close')
  }
}

async function bootstrapApp() {
  const pinia = createPinia()
  setActivePinia(pinia)
  i18n.global.locale.value = 'en-US'
  const auth = useAuthStore(pinia)
  await auth.bootstrap()
  return pinia
}

async function mountApp(pinia: ReturnType<typeof createPinia>, path = '/') {
  await router.push(path)
  await router.isReady()
  const wrapper = mount(App, {
    attachTo: document.body,
    global: { plugins: [pinia, i18n, router] },
  })
  activeWrapper = wrapper
  await settle(10)
  return wrapper
}

describe('application shell', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
    localStorage.clear()
    FakeSocket.instances = []
    vi.stubGlobal('WebSocket', FakeSocket)
    installFetchMock()
  })
  afterEach(() => {
    activeWrapper?.unmount()
    activeWrapper = null
    document.body.innerHTML = ''
    vi.unstubAllGlobals()
  })

  it('renders the server shell and navigates every server route', async () => {
    const wrapper = await mountApp(await bootstrapApp())
    expect(wrapper.text()).toContain('Ostium')
    expect(wrapper.text()).toContain('Overview')

    const socket = FakeSocket.instances[0]
    socket.emit('open')
    socket.emit('message', {
      data: JSON.stringify({ type: 'alert.created', ts: 'now', data: { message: 'alert' } }),
    })
    socket.emit('message', {
      data: JSON.stringify({
        type: 'job.updated',
        ts: 'now',
        data: { status: 'succeeded', type: 'backup.create', id: 'job-1' },
      }),
    })

    for (const path of [
      '/inbounds',
      '/users',
      '/subscriptions',
      '/connections',
      '/rules',
      '/certificates',
      '/logs',
      '/jobs',
      '/system',
      '/audit',
      '/settings',
      '/missing-page',
    ]) {
      await router.push(path)
      await settle(4)
      expect(wrapper.html()).toBeTruthy()
    }

    // Keyboard shortcuts and global search.
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }))
    await settle(2)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'g', bubbles: true }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'u', bubbles: true }))
    await settle(2)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'c', bubbles: true }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }))
    await settle(2)

    // Exercise layout controls: theme, language, sidebar, alerts, user menu.
    const buttons = Array.from(document.querySelectorAll('button'))
    for (const button of buttons) {
      if ((button as HTMLButtonElement).disabled) continue
      ;(button as HTMLButtonElement).click()
      await settle(1)
    }
    expect(wrapper.html()).toBeTruthy()
  })

  it('renders the client shell and client routes', async () => {
    installFetchMock({ role: 'client' })
    const wrapper = await mountApp(await bootstrapApp())
    expect(wrapper.text()).toContain('Home')

    for (const path of [
      '/profiles',
      '/routing',
      '/network',
      '/stats',
      '/diagnostics',
      '/settings',
    ]) {
      await router.push(path)
      await settle(4)
      expect(wrapper.html()).toBeTruthy()
    }

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'c', bubbles: true }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'g', bubbles: true }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'p', bubbles: true }))
    await settle(2)
    expect(wrapper.html()).toBeTruthy()
  })

  it('handles unauthenticated and uninitialized routing', async () => {
    installFetchMock({
      overrides: {
        '/api/v1/auth/status': {
          initialized: false,
          has_admin: false,
          authenticated: false,
          must_change_password: false,
          totp_enabled: false,
          role: 'server',
          version: '0.1.0',
          public_ui: false,
        },
      },
    })
    await bootstrapApp()
    await router.push('/users')
    await router.isReady()
    expect(router.currentRoute.value.name).toBe('setup')
  })
})
