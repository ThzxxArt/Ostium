import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

const base = {
  initialized: true,
  has_admin: true,
  authenticated: false,
  must_change_password: false,
  totp_enabled: false,
  role: 'server' as const,
  version: '0.1.0',
  public_ui: false,
}

describe('router guards', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('redirects uninitialised installs to setup and setup away when signed in', async () => {
    const auth = useAuthStore()
    auth.status = { ...base, initialized: false }
    auth.ready = true
    await router.push('/users')
    expect(router.currentRoute.value.name).toBe('setup')

    auth.status = { ...base, authenticated: true }
    await router.push('/')
    await router.push('/setup')
    expect(router.currentRoute.value.path).toBe('/')

    await router.push('/login')
    expect(router.currentRoute.value.path).toBe('/')
  })

  it('enforces authentication and roles', async () => {
    const auth = useAuthStore()
    auth.status = { ...base, authenticated: false }
    auth.ready = true
    await router.push('/users')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.next).toBe('/users')

    auth.status = { ...base, authenticated: true, role: 'server' }
    await router.push('/profiles')
    expect(router.currentRoute.value.path).toBe('/')

    auth.status = { ...base, authenticated: true, role: 'client' }
    await router.push('/profiles')
    expect(router.currentRoute.value.path).toBe('/profiles')
  })

  it('sets document titles for server and client homes', async () => {
    const auth = useAuthStore()
    auth.status = { ...base, authenticated: true, role: 'server' }
    auth.ready = true
    await router.push('/')
    expect(document.title).toContain('Overview')
    auth.status = { ...base, authenticated: true, role: 'client' }
    await router.push('/')
    expect(document.title.toLowerCase()).toContain('home')
  })
})
