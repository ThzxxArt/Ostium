import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { useRegisterSW } from '@/composables/usePwa'

interface FakeReg {
  waiting: { postMessage: ReturnType<typeof vi.fn> } | null
  installing: { state: string; addEventListener: ReturnType<typeof vi.fn> } | null
  addEventListener: ReturnType<typeof vi.fn>
  update: ReturnType<typeof vi.fn>
}

function fakeServiceWorker() {
  const listeners = new Map<string, () => void>()
  const registration: FakeReg = {
    waiting: null,
    installing: null,
    addEventListener: vi.fn((name: string, callback: () => void) => {
      listeners.set(name, callback)
    }),
    update: vi.fn(async () => undefined),
  }
  const controllerListeners = new Map<string, () => void>()
  const container = {
    controller: {} as ServiceWorker | null,
    register: vi.fn(async () => registration as unknown as ServiceWorkerRegistration),
    addEventListener: vi.fn((name: string, callback: () => void) => {
      controllerListeners.set(name, callback)
    }),
  }
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: container,
  })
  return { container, registration, listeners, controllerListeners }
}

function mountPwa(options: Parameters<typeof useRegisterSW>[0] = {}) {
  let api: ReturnType<typeof useRegisterSW> | null = null
  const component = defineComponent({
    setup() {
      api = useRegisterSW(options)
      return () => h('div')
    },
  })
  const wrapper = mount(component)
  return { wrapper, api: () => api }
}

describe('PWA registration', () => {
  beforeEach(() => {
    vi.useRealTimers()
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('registers a worker and exposes an existing waiting update', async () => {
    const { registration } = fakeServiceWorker()
    const waiting = { postMessage: vi.fn() }
    registration.waiting = waiting
    const onRegisteredSW = vi.fn()
    const { wrapper, api } = mountPwa({ onRegisteredSW })
    await flushPromises()
    await nextTick()

    expect(navigator.serviceWorker.register).toHaveBeenCalledWith('/sw.js')
    expect(onRegisteredSW).toHaveBeenCalledWith('/sw.js', registration)
    expect(api()?.needRefresh.value).toBe(true)

    await api()?.updateServiceWorker(false)
    expect(waiting.postMessage).toHaveBeenCalledWith({ type: 'SKIP_WAITING' })
    wrapper.unmount()
  })

  it('detects a newly installed worker while the page is controlled', async () => {
    const { container, registration, listeners } = fakeServiceWorker()
    container.controller = {} as ServiceWorker
    const { wrapper, api } = mountPwa()
    await flushPromises()

    const installedListener = vi.fn()
    registration.installing = {
      state: 'installing',
      addEventListener: vi.fn((_name: string, callback: () => void) => {
        installedListener.mockImplementation(callback)
      }),
    }
    listeners.get('updatefound')?.()
    registration.installing.state = 'installed'
    installedListener()
    await nextTick()
    expect(api()?.needRefresh.value).toBe(true)
    wrapper.unmount()
  })

  it('reports registration errors and works without service workers', async () => {
    const { container } = fakeServiceWorker()
    const error = new Error('denied')
    container.register.mockRejectedValueOnce(error)
    const onRegisterError = vi.fn()
    const first = mountPwa({ onRegisterError })
    await flushPromises()
    expect(onRegisterError).toHaveBeenCalledWith(error)
    first.wrapper.unmount()

    Reflect.deleteProperty(navigator, 'serviceWorker')
    const second = mountPwa()
    await flushPromises()
    expect(second.api()?.offlineReady.value).toBe(true)
    second.wrapper.unmount()
  })
})
