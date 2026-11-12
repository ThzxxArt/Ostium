import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import OPwaUpdate from '@/components/OPwaUpdate.vue'
import { i18n } from '@/locales'

const pwa = vi.hoisted(() => ({
  needRefresh: null as any,
  updateServiceWorker: vi.fn(async () => undefined),
}))

vi.mock('virtual:pwa-register/vue', async () => {
  const { ref: vueRef } = await import('vue')
  pwa.needRefresh = vueRef(true)
  return {
    useRegisterSW: () => ({
      needRefresh: pwa.needRefresh,
      updateServiceWorker: pwa.updateServiceWorker,
    }),
  }
})

describe('PWA update prompt', () => {
  beforeEach(() => {
    pwa.needRefresh.value = true
    pwa.updateServiceWorker.mockClear()
    document.body.innerHTML = ''
  })
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('reloads or dismisses the update prompt', async () => {
    const wrapper = mount(OPwaUpdate, { global: { plugins: [createPinia(), i18n] } })
    await nextTick()
    expect(wrapper.text()).toContain('A new version is ready')
    await wrapper.find('.pwa-update button').trigger('click')
    await nextTick()
    expect(pwa.updateServiceWorker).toHaveBeenCalledWith(true)

    await wrapper.find('.pwa-update .dismiss').trigger('click')
    await nextTick()
    expect(wrapper.html()).toBeTruthy()
    pwa.needRefresh.value = false
    await nextTick()
    wrapper.unmount()
  })

  it('keeps the prompt hidden when no update is available', async () => {
    pwa.needRefresh.value = false
    const wrapper = mount(OPwaUpdate, { global: { plugins: [createPinia(), i18n] } })
    await nextTick()
    expect(wrapper.text()).not.toContain('A new version is ready')
    wrapper.unmount()
  })
})
