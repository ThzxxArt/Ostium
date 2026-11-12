import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import {
  NConfigProvider,
  NDialogProvider,
  NLoadingBarProvider,
  NMessageProvider,
  NNotificationProvider,
} from 'naive-ui'
import { i18n } from '@/locales'
import { useBrowserNotifications } from '@/composables/useBrowserNotifications'
import { useCopy } from '@/composables/useCopy'
import { useStatus } from '@/composables/useStatus'
import { useAuthStore } from '@/stores/auth'
import { installFetchMock, mountPage, settle, cleanupPage } from './helpers'

function mountWithProviders(component: any) {
  const Host = defineComponent({
    render: () =>
      h(
        NConfigProvider,
        { abstract: true },
        {
          default: () =>
            h(NLoadingBarProvider, null, {
              default: () =>
                h(NDialogProvider, null, {
                  default: () =>
                    h(NNotificationProvider, null, {
                      default: () => h(NMessageProvider, null, { default: () => h(component) }),
                    }),
                }),
            }),
        },
      ),
  })
  return mount(Host, { global: { plugins: [createPinia(), i18n] } })
}

describe('composables', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
  })
  afterEach(() => {
    cleanupPage()
    vi.unstubAllGlobals()
  })

  it('copies with clipboard and both fallbacks', async () => {
    const writeText = vi.fn(async () => undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    const Page = defineComponent({
      setup() {
        const { copy } = useCopy()
        return () => h('button', { onClick: () => void copy('hello') }, 'copy')
      },
    })
    const wrapper = mountWithProviders(Page)
    await wrapper.find('button').trigger('click')
    await settle()
    expect(writeText).toHaveBeenCalledWith('hello')

    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: async () => Promise.reject(new Error('denied')) },
    })
    Object.defineProperty(document, 'execCommand', { configurable: true, value: () => true })
    await wrapper.find('button').trigger('click')
    await settle()

    Object.defineProperty(document, 'execCommand', { configurable: true, value: () => false })
    await wrapper.find('button').trigger('click')
    await settle()

    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: () => {
        throw new Error('blocked')
      },
    })
    await wrapper.find('button').trigger('click')
    await settle()
    wrapper.unmount()
  })

  it('handles unsupported, denied, granted and unruly notifications', async () => {
    // @ts-expect-error test cleanup
    delete window.Notification
    const unsupported = useBrowserNotifications()
    expect(unsupported.supported).toBe(false)
    expect(await unsupported.request()).toBe(false)
    unsupported.notify('title', 'body')

    const requestPermission = vi.fn(async () => 'denied' as NotificationPermission)
    class DeniedNotification {
      static permission: NotificationPermission = 'default'
      static requestPermission = requestPermission
    }
    vi.stubGlobal('Notification', DeniedNotification)
    Object.defineProperty(window, 'Notification', { configurable: true, value: DeniedNotification })
    const denied = useBrowserNotifications()
    expect(await denied.request()).toBe(false)
    denied.notify('title', 'body')

    const granted = vi.fn()
    class GrantedNotification {
      static permission: NotificationPermission = 'default'
      static requestPermission = vi.fn(async () => 'granted' as NotificationPermission)
      constructor(title: string, options: NotificationOptions) {
        granted(title, options)
      }
    }
    vi.stubGlobal('Notification', GrantedNotification)
    Object.defineProperty(window, 'Notification', {
      configurable: true,
      value: GrantedNotification,
    })
    const allowed = useBrowserNotifications()
    expect(await allowed.request()).toBe(true)
    allowed.notify('hello', 'world', 'tag')
    expect(granted).toHaveBeenCalled()

    GrantedNotification.permission = 'granted'
    const already = useBrowserNotifications()
    expect(await already.request()).toBe(true)

    class BrokenNotification {
      static permission: NotificationPermission = 'granted'
      static requestPermission = vi.fn(async () => 'granted' as NotificationPermission)
      constructor() {
        throw new Error('unsupported')
      }
    }
    vi.stubGlobal('Notification', BrokenNotification)
    Object.defineProperty(window, 'Notification', { configurable: true, value: BrokenNotification })
    const broken = useBrowserNotifications()
    expect(() => broken.notify('x', 'y')).not.toThrow()
  })

  it('refreshes and stops system status', async () => {
    installFetchMock()
    const Page = defineComponent({
      setup() {
        const status = useStatus()
        return { status }
      },
      template: '<div>{{ status.mode.value }}</div>',
    })
    const { wrapper } = await mountPage(Page, {}, (pinia) => {
      const auth = useAuthStore(pinia)
      auth.status = {
        initialized: true,
        has_admin: true,
        authenticated: true,
        must_change_password: false,
        totp_enabled: true,
        role: 'server',
        version: '0.1.0',
        public_ui: false,
      }
      auth.ready = true
    })
    await settle()
    const status = (wrapper.findComponent(Page).vm as any).status
    expect(status.coreRunning.value).toBe(true)
    expect(status.serverHost.value).toBe('vpn.example.com')

    installFetchMock({ mode: 'error' })
    await status.refresh()
    expect(status.coreReachable.value).toBe(false)
    wrapper.unmount()
  })
})
