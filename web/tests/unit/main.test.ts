import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { installFetchMock } from './helpers'

vi.mock('@/App.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      setup() {
        return () => h('div', { id: 'mock-app' }, 'Ostium')
      },
    }),
  }
})

vi.mock('@/router', () => ({
  default: {
    install() {},
    isReady: async () => undefined,
  },
}))

class FakeSocket {
  addEventListener() {}
  close() {}
}

describe('application bootstrap', () => {
  beforeEach(() => {
    vi.resetModules()
    document.body.innerHTML = '<div id="app"></div>'
    document.cookie = 'ostium_csrf=token; path=/'
    vi.stubGlobal('WebSocket', FakeSocket)
    installFetchMock()
  })
  afterEach(() => {
    document.body.innerHTML = ''
    vi.unstubAllGlobals()
  })

  it('mounts the Vue application into #app', async () => {
    await import('@/main')
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(document.querySelector('#app')?.children.length).toBeGreaterThan(0)
  })
})
