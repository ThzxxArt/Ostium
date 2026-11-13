import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import OStatCard from '@/components/OStatCard.vue'
import OErrorBoundary from '@/components/OErrorBoundary.vue'
import { i18n } from '@/locales'
import { http } from '@/api/client'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('v0.1.1 shared components', () => {
  it('renders every stat tone and both loading states', () => {
    for (const tone of ['accent', 'info', 'success', 'warning', 'danger', 'neutral'] as const) {
      const wrapper = mount(OStatCard, {
        props: { label: 'Users', value: 3, unit: 'online', hint: 'today', tone },
        global: { plugins: [i18n] },
      })
      expect(wrapper.classes()).toContain(`tone-${tone}`)
      expect(wrapper.text()).toContain('online')
    }
    const loading = mount(OStatCard, {
      props: { label: 'Loading', value: 0, loading: true },
      global: { plugins: [i18n] },
    })
    expect(loading.find('.skeleton').exists()).toBe(true)
    expect(loading.find('.value').exists()).toBe(false)
  })

  it('shows a recovery card when a child throws', async () => {
    const Broken = defineComponent({
      setup() {
        throw new Error('boom')
      },
      render: () => h('div'),
    })
    const wrapper = mount(OErrorBoundary, {
      slots: { default: () => h(Broken) },
      global: { plugins: [i18n] },
    })
    await nextTick()
    expect(wrapper.text()).toContain('failed to render')
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  })

  it('dispatches an unauthorized event for 401 responses', async () => {
    const listener = vi.fn()
    window.addEventListener('ostium:unauthorized', listener)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 401,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ detail: 'expired', code: 'session_expired' }),
      })),
    )
    await expect(http.get('/api/v1/users')).rejects.toThrow('expired')
    expect(listener).toHaveBeenCalled()
    window.removeEventListener('ostium:unauthorized', listener)
  })

  it('does not redirect for login failures', async () => {
    const listener = vi.fn()
    window.addEventListener('ostium:unauthorized', listener)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 401,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ detail: 'bad password', code: 'invalid_credentials' }),
      })),
    )
    await expect(http.post('/api/v1/auth/login', {})).rejects.toThrow('bad password')
    expect(listener).not.toHaveBeenCalled()
    window.removeEventListener('ostium:unauthorized', listener)
  })
})
