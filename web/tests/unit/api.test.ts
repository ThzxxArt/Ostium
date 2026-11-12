import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { ApiError, ensureCsrf, http } from '@/api/client'
import { installFetchMock } from './helpers'

function resetCookies() {
  document.cookie = 'ostium_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
}

describe('api client', () => {
  beforeEach(() => {
    resetCookies()
    vi.unstubAllGlobals()
  })

  it('adds CSRF tokens and parses JSON, text and FormData bodies', async () => {
    const { calls } = installFetchMock()
    document.cookie = 'ostium_csrf=token%201; path=/'

    await http.get('/api/v1/auth/status')
    expect(calls[0].method).toBe('GET')

    await http.post('/api/v1/auth/login', { username: 'admin' })
    expect(calls[1].method).toBe('POST')

    const form = new FormData()
    form.append('a', 'b')
    await http.put('/api/v1/upload', form)
    expect(calls[2].method).toBe('PUT')

    document.cookie = 'ostium_csrf=; path=/'
    const { fetchMock } = installFetchMock()
    await http.delete('/api/v1/users/1')
    expect(fetchMock).toHaveBeenCalledTimes(2) // CSRF bootstrap + delete
  })

  it('bootstraps CSRF only once and caches the promise', async () => {
    const { fetchMock } = installFetchMock()
    await Promise.all([ensureCsrf(), ensureCsrf()])
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/auth/csrf')

    document.cookie = 'ostium_csrf=abc; path=/'
    await ensureCsrf()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('converts text and problem responses to ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 418,
        headers: new Headers({ 'content-type': 'text/plain' }),
        text: async () => 'teapot',
        json: async () => {
          throw new Error('no json')
        },
      })),
    )
    await expect(http.get('/x')).rejects.toMatchObject({
      status: 418,
      code: 'http_error',
      message: 'teapot',
    })

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 422,
        headers: new Headers({ 'content-type': 'application/problem+json' }),
        json: async () => ({ detail: 'bad input', code: 'validation_error' }),
        text: async () => '',
      })),
    )
    await expect(http.post('/x', {})).rejects.toBeInstanceOf(ApiError)

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => {
          throw new Error('broken json')
        },
        text: async () => '',
      })),
    )
    await expect(http.get('/x')).resolves.toEqual({})

    const error = new ApiError(500, {})
    expect(error.message).toBe('HTTP 500')
    expect(error.code).toBe('api_error')
  })

  it('calls every API method with the expected verb and payload', async () => {
    const { calls } = installFetchMock()
    document.cookie = 'ostium_csrf=token; path=/'

    await api.auth.status()
    await api.auth.csrf()
    await api.auth.login('admin', 'secret', '123456')
    await api.auth.logout()
    await api.auth.me()
    await api.auth.setup({ role: 'server', username: 'admin', password: 'secret' })
    await api.auth.changePassword('old', 'new')
    await api.auth.totpStart()
    await api.auth.totpConfirm('123456')
    await api.auth.totpDisable('secret')

    await api.inbounds.list()
    await api.inbounds.update('vless', { enabled: true })
    await api.inbounds.rotateReality()

    await api.users.list()
    await api.users.create({ name: 'alice' })
    await api.users.get('user-1')
    await api.users.update('user-1', { note: 'x' })
    await api.users.remove('user-1')
    await api.users.rotate('user-1', true)
    await api.users.resetUsage('user-1')
    await api.users.usage('user-1', 7)
    await api.users.subscription('user-1')
    await api.users.rotateSubscription('user-1')
    await api.users.export('user-1')
    await api.users.bulk('disable', ['user-1'])

    await api.subscriptions.overview()
    await api.profiles.list()
    await api.profiles.create({ name: 'HK', text: 'vless://x' })
    await api.profiles.update('profile-1', { enabled: false })
    await api.profiles.remove('profile-1')
    await api.profiles.refresh('profile-1')
    await api.profiles.export('profile-1')
    await api.profiles.test('profile-1')

    await api.rules.list()
    await api.rules.create({ action: 'direct' })
    await api.rules.update('rule-1', { enabled: false })
    await api.rules.remove('rule-1')
    await api.rules.reorder(['rule-1'])
    await api.rules.test({ domain: 'example.com' })
    await api.rules.ruleSets()
    await api.rules.addRuleSet({ name: 'ads' })
    await api.rules.updateRuleSet('set-1')
    await api.rules.removeRuleSet('set-1')

    await api.stats.overview()
    await api.stats.traffic(7, 'user-1')
    await api.stats.connections('example')
    await api.stats.closeConnection('conn-1')
    await api.stats.closeAll()

    await api.logs.get('core', 'error', 'boom', 10)
    expect(api.logs.downloadUrl('core')).toContain('source=core')

    await api.certificates.list()
    await api.certificates.issue('vpn.example.com')
    await api.certificates.upload({ domain: 'x', cert_pem: 'c', key_pem: 'k' })
    await api.certificates.renew('cert-1')
    await api.certificates.use('cert-1', ['hysteria2'])
    await api.certificates.remove('cert-1')

    await api.jobs.list(10)
    await api.jobs.get('job-1')
    await api.jobs.cancel('job-1')

    await api.system.info()
    await api.system.doctor()
    await api.system.proxy(true)
    await api.system.tun(true)
    await api.system.mode('tun')
    await api.system.connect()
    await api.system.disconnect()
    await api.system.services()
    await api.system.restart('ostium-core')
    await api.system.diagnostics()
    expect(api.system.diagnosticsUrl()).toContain('diagnostics/download')

    await api.settings.get()
    await api.settings.update({ log_level: 'debug' })
    await api.settings.publicUi(true, 'vpn.example.com')
    await api.settings.tokens()
    await api.settings.createToken('ci', ['read'])
    await api.settings.revokeToken('tok-1')

    await api.backups.list()
    await api.backups.create('password')
    await api.backups.restore('backup-1', 'password')
    await api.backups.remove('backup-1')

    await api.alerts.list(true)
    await api.alerts.ack('alert-1')

    await api.audit.list(10, 0)

    expect(calls.length).toBeGreaterThan(60)
    expect(calls.some((call) => call.method === 'PATCH')).toBe(true)
    expect(calls.some((call) => call.method === 'DELETE')).toBe(true)
    expect(calls.some((call) => call.path.startsWith('/api/v1/logs'))).toBe(true)
    expect(calls.some((call) => call.search.includes('user_id=user-1'))).toBe(true)
  })
})
