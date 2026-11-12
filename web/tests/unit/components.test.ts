import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { i18n } from '@/locales'
import OShortcutModal from '@/components/OShortcutModal.vue'
import OSkeletonPage from '@/components/OSkeletonPage.vue'
import OTrafficChart from '@/components/OTrafficChart.vue'
import OLazyChart from '@/components/OLazyChart.vue'
import OCopyButton from '@/components/OCopyButton.vue'
import OJobDrawer from '@/components/OJobDrawer.vue'
import OCommandPalette from '@/components/OCommandPalette.vue'
import OConnectOrb from '@/components/OConnectOrb.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import OSectionCard from '@/components/OSectionCard.vue'
import OStatCard from '@/components/OStatCard.vue'
import OPageHeader from '@/components/OPageHeader.vue'
import OErrorState from '@/components/OErrorState.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import { useAppStore } from '@/stores/app'

vi.mock('vue-echarts', () => ({
  default: {
    name: 'VChart',
    props: ['option', 'autoresize'],
    template: '<div class="vchart" />',
  },
}))
import {
  cleanupPage,
  clickAllButtons,
  clickByText,
  installFetchMock,
  mountPage,
  settle,
} from './helpers'

describe('components', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
  })
  afterEach(() => {
    cleanupPage()
    vi.unstubAllGlobals()
  })

  it('renders the shortcut modal', async () => {
    const { pinia } = await mountPage(OShortcutModal)
    const app = useAppStore(pinia)
    app.shortcutsOpen = true
    await settle()
    expect(document.body.textContent).toContain('Open command palette')
    app.shortcutsOpen = false
    await settle()
    expect(app.shortcutsOpen).toBe(false)
  })

  it('renders skeleton rows and cards', async () => {
    const { wrapper } = await mountPage(OSkeletonPage, { cards: 2, rows: 2 })
    expect(wrapper.findAll('.card')).toHaveLength(2)
    expect(wrapper.findAll('.row')).toHaveLength(2)
  })

  it('renders chart options for both themes and empty data', async () => {
    const { wrapper, pinia } = await mountPage(OTrafficChart, {
      series: [{ day: '2026-01-01', up: 10, down: 20 }],
    })
    await settle()
    expect(wrapper.html()).toBeTruthy()
    const app = useAppStore(pinia)
    app.setTheme('light')
    await settle()
    app.setTheme('dark')
    await settle()
    cleanupPage()
    const empty = await mountPage(OTrafficChart, { series: [] })
    expect(empty.wrapper.text()).toContain('No traffic data')
  })

  it('lazily renders traffic charts', async () => {
    let callback: any = null
    class Observer {
      constructor(cb: (entries: Array<{ isIntersecting: boolean }>) => void) {
        callback = cb
      }
      observe() {}
      disconnect() {}
    }
    vi.stubGlobal('IntersectionObserver', Observer)
    Object.defineProperty(window, 'IntersectionObserver', { configurable: true, value: Observer })
    const { wrapper } = await mountPage(OLazyChart, {
      series: [{ day: '2026-01-01', up: 1, down: 2 }],
    })
    expect(wrapper.find('.placeholder').exists()).toBe(true)
    callback?.([{ isIntersecting: true }])
    await settle()
    expect(wrapper.html()).toBeTruthy()

    cleanupPage()
    // @ts-expect-error test cleanup
    delete window.IntersectionObserver
    const second = await mountPage(OLazyChart, { series: [{ day: '2026-01-01', up: 1, down: 2 }] })
    await settle()
    expect(second.wrapper.html()).toBeTruthy()
  })

  it('copies with clipboard and fallbacks', async () => {
    const writeText = vi.fn(async () => undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    const { wrapper } = await mountPage(OCopyButton, { value: 'secret', label: 'Copy' })
    await wrapper.find('button').trigger('click')
    await settle()
    expect(writeText).toHaveBeenCalledWith('secret')

    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async () => {
          throw new Error('denied')
        },
      },
    })
    const exec = vi.fn(() => true)
    Object.defineProperty(document, 'execCommand', { configurable: true, value: exec })
    const fallback = await mountPage(OCopyButton, { value: 'fallback' })
    await fallback.wrapper.find('button').trigger('click')
    await settle()
    expect(exec).toHaveBeenCalled()

    Object.defineProperty(document, 'execCommand', { configurable: true, value: () => false })
    const failed = await mountPage(OCopyButton, { value: 'failed', size: 'tiny', block: true })
    await failed.wrapper.find('button').trigger('click')
    await settle()
    expect(failed.wrapper.find('button').exists()).toBe(true)
  })

  it('loads and cancels jobs in the drawer', async () => {
    installFetchMock()
    const wrapper = mount(OJobDrawer, {
      props: { show: false },
      global: { plugins: [createPinia(), i18n] },
    })
    await wrapper.setProps({ show: true })
    await settle()
    expect(document.body.textContent).toContain('backup.create')
    await clickByText('Cancel')
    await clickAllButtons(1)
    expect(document.body.textContent).toContain('acme.issue')

    installFetchMock({ mode: 'error' })
    await wrapper.setProps({ show: false })
    await wrapper.setProps({ show: true })
    await settle()
    expect(document.body.textContent).toContain('simulated failure')

    installFetchMock({ mode: 'empty' })
    await wrapper.setProps({ show: false })
    await wrapper.setProps({ show: true })
    await settle()
    expect(document.body.textContent).toContain('No jobs')
    wrapper.unmount()
  })

  it('drives the command palette with keyboard and mouse', async () => {
    installFetchMock()
    const { wrapper, pinia } = await mountPage(OCommandPalette)
    const app = useAppStore(pinia)
    app.commandOpen = true
    await settle()
    const input = document.querySelector('.palette input') as HTMLInputElement
    expect(input).toBeTruthy()
    input.value = 'users'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await settle()
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }))
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await settle()
    app.commandOpen = true
    await settle()
    const item = document.querySelector('.palette .item') as HTMLElement
    item?.click()
    await settle()
    app.commandOpen = true
    await settle()
    input.value = 'zzzz-no-match'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await settle()
    expect(document.body.textContent).toContain('No matches')
    app.commandOpen = false
    expect(wrapper.html()).toBeTruthy()
  })

  it('renders visual variants of small components', async () => {
    for (const state of ['connected', 'connecting', 'disconnected'] as const) {
      const orb = await mountPage(OConnectOrb, {
        state,
        label: state,
        sublabel: 'sublabel',
        disabled: state === 'connecting',
      })
      expect(orb.wrapper.text()).toContain(state)
      cleanupPage()
    }

    for (const status of ['success', 'warning', 'danger', 'info', 'neutral']) {
      const pill = await mountPage(OStatusPill, { status, label: status, pulse: true })
      expect(pill.wrapper.html()).toBeTruthy()
      cleanupPage()
    }
    const section = await mountPage(OSectionCard, { title: 'Section', padding: 'compact' })
    expect(section.wrapper.text()).toContain('Section')
    cleanupPage()
    const stat = await mountPage(OStatCard, { label: 'Users', value: '10', tone: 'accent' })
    expect(stat.wrapper.text()).toContain('Users')
    cleanupPage()
    const header = await mountPage(OPageHeader, { title: 'Title', subtitle: 'Subtitle' })
    expect(header.wrapper.text()).toContain('Title')
    cleanupPage()
    const error = await mountPage(OErrorState, { message: 'failed' })
    await error.wrapper.find('button').trigger('click')
    expect(error.wrapper.findComponent(OErrorState).emitted('retry')).toBeTruthy()
    cleanupPage()
    const empty = await mountPage(OEmptyState, { title: 'Empty', description: 'Nothing' })
    expect(empty.wrapper.text()).toContain('Empty')
  })
})
