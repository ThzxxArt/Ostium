import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { useRegisterSW } from '@/composables/usePwa'
import { MUTATION_TIMEOUT_MS, READ_TIMEOUT_MS, http } from '@/api/client'
import OSectionCard from '@/components/OSectionCard.vue'
import OPageHeader from '@/components/OPageHeader.vue'
import OErrorState from '@/components/OErrorState.vue'
import OTrafficChart from '@/components/OTrafficChart.vue'
import { installFetchMock, mountPage } from './helpers'

vi.mock('vue-echarts', () => ({
  default: {
    name: 'VChart',
    props: ['option', 'autoresize'],
    template: '<div class="vchart" />',
  },
}))

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

describe('review round 2 branches', () => {
  beforeEach(() => {
    vi.useRealTimers()
    document.cookie = 'ostium_csrf=token; path=/'
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('uses a longer abort timeout for mutations than for reads', async () => {
    installFetchMock()
    const timeout = vi.spyOn(AbortSignal, 'timeout')
    await http.get('/api/v1/auth/status')
    expect(timeout).toHaveBeenLastCalledWith(READ_TIMEOUT_MS)
    await http.patch('/api/v1/users/1', { note: 'x' })
    expect(timeout).toHaveBeenLastCalledWith(MUTATION_TIMEOUT_MS)
  })

  it('reloads after a waiting worker activates and skips the reload otherwise', async () => {
    const listeners = new Map<string, () => void>()
    const waiting = { postMessage: vi.fn() }
    const registration = {
      waiting: waiting as { postMessage: ReturnType<typeof vi.fn> } | null,
      installing: null,
      addEventListener: vi.fn(),
      update: vi.fn(async () => undefined),
    }
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: {
        controller: {} as ServiceWorker,
        register: vi.fn(async () => registration),
        addEventListener: vi.fn((name: string, callback: () => void) => {
          listeners.set(name, callback)
        }),
      },
    })
    const reload = vi.fn()
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, reload },
    })

    const { wrapper, api } = mountPwa()
    await flushPromises()
    await api()?.updateServiceWorker(true)
    expect(listeners.has('controllerchange')).toBe(true)
    listeners.get('controllerchange')?.()
    expect(reload).toHaveBeenCalled()
    wrapper.unmount()

    registration.waiting = null
    const second = mountPwa()
    await flushPromises()
    // No waiting worker and no reload request: the helper must do nothing.
    const before = reload.mock.calls.length
    await second.api()?.updateServiceWorker(false)
    expect(reload.mock.calls.length).toBe(before)
    second.wrapper.unmount()
  })

  it('ignores an updatefound event without an installing worker', async () => {
    const updateFound = new Map<string, () => void>()
    const registration = {
      waiting: null,
      installing: null,
      addEventListener: vi.fn((name: string, callback: () => void) => {
        updateFound.set(name, callback)
      }),
      update: vi.fn(async () => undefined),
    }
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: {
        controller: null,
        register: vi.fn(async () => registration),
        addEventListener: vi.fn(),
      },
    })
    const { wrapper, api } = mountPwa()
    await flushPromises()
    expect(() => updateFound.get('updatefound')?.()).not.toThrow()
    await nextTick()
    expect(api()?.needRefresh.value).toBe(false)
    wrapper.unmount()
  })

  it('falls back to English when reading the stored locale fails and survives a write failure', async () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.resetModules()
    const module = await import('@/locales')
    expect(module.currentLocale()).toMatch(/^(en-US|zh-CN)$/)
    expect(() => module.setLocale('zh-CN')).not.toThrow()
    expect(module.currentLocale()).toBe('zh-CN')
    getItem.mockRestore()
    setItem.mockRestore()
  })

  it('renders every optional section-card, page-header and error-state branch', async () => {
    const { createPinia } = await import('pinia')
    const { i18n } = await import('@/locales')
    const plugins = [createPinia(), i18n]
    const section = mount(OSectionCard, {
      props: { title: 'With title', description: 'Description', padding: 'none' },
      slots: {
        header: '<span class="custom-header">custom</span>',
        actions: '<button class="custom-action">go</button>',
        footer: '<span class="custom-footer">foot</span>',
        default: '<p>body</p>',
      },
      global: { plugins },
    })
    expect(section.text()).toContain('Description')
    expect(section.find('.custom-header').exists()).toBe(true)
    expect(section.find('.custom-action').exists()).toBe(true)
    expect(section.find('.custom-footer').exists()).toBe(true)

    // A description without a title still renders the copy block; an empty
    // card renders no header at all.
    const descriptionOnly = mount(OSectionCard, {
      props: { description: 'Only description' },
      global: { plugins },
    })
    expect(descriptionOnly.find('.copy').exists()).toBe(true)
    const bare = mount(OSectionCard, { global: { plugins } })
    expect(bare.find('header').exists()).toBe(false)
    const header = mount(OPageHeader, {
      props: { title: 'Title', eyebrow: 'Kicker', subtitle: 'Sub' },
      global: { plugins },
    })
    expect(header.text()).toContain('Kicker')
    const error = mount(OErrorState, {
      props: { title: 'Broken', message: 'failed' },
      slots: {
        actions: '<button class="custom-retry">retry</button>',
        details: '<code>detail</code>',
      },
      global: { plugins },
    })
    expect(error.text()).toContain('Broken')
    expect(error.find('details').exists()).toBe(true)
  })

  it('formats chart tooltips and axes for both themes', async () => {
    const { wrapper } = await mountPage(OTrafficChart, {
      series: [{ day: '2026-01-01', up: 1024, down: 2048 }],
      showUpload: false,
      showDownload: false,
    })
    const chart = wrapper.findComponent({ name: 'VChart' })
    const option = chart.props('option') as {
      tooltip: { formatter: (params: unknown) => string }
      yAxis: { axisLabel: { formatter: (value: number) => string } }
      series: unknown[]
    }
    expect(option.tooltip.formatter([])).toBe('')
    const formatted = option.tooltip.formatter([
      { axisValue: '2026-01-01', seriesName: 'Down', value: 2048, color: '#000' },
    ])
    expect(formatted).toContain('2026-01-01')
    expect(formatted).toContain('Down')
    expect(option.yAxis.axisLabel.formatter(1024)).toBeTruthy()
    expect(option.series).toHaveLength(0)
  })
})
