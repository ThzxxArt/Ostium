import { defineComponent, h, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import {
  NConfigProvider,
  NDialogProvider,
  NLoadingBarProvider,
  NMessageProvider,
  NNotificationProvider,
} from 'naive-ui'
import { i18n } from '@/locales'

const T = '2026-01-01T10:00:00Z'

export const fixtures = {
  status: {
    initialized: true,
    has_admin: true,
    authenticated: true,
    must_change_password: false,
    totp_enabled: true,
    role: 'server' as const,
    version: '0.1.0',
    public_ui: false,
  },
  me: {
    id: 'admin-1',
    username: 'admin',
    must_change_password: false,
    totp_enabled: true,
    recovery_codes_remaining: 9,
    last_login_at: T,
    role: 'server' as const,
  },
  user: {
    id: 'user-1',
    name: 'alice',
    enabled: true,
    uuid: '2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e',
    expires_at: '2027-01-01T00:00:00Z',
    quota_bytes: 10 * 1024 ** 3,
    quota_cycle: 'monthly' as const,
    cycle_started_at: T,
    used_bytes: 2 * 1024 ** 3,
    note: 'primary',
    status: 'active',
    online: true,
    last_seen_at: T,
    created_at: T,
    disabled_reason: null,
    has_subscription: true,
  },
  disabledUser: {
    id: 'user-2',
    name: 'bob',
    enabled: false,
    uuid: '2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0f',
    expires_at: null,
    quota_bytes: 0,
    quota_cycle: 'total' as const,
    cycle_started_at: T,
    used_bytes: 0,
    note: '',
    status: 'disabled',
    online: false,
    last_seen_at: null,
    created_at: T,
    disabled_reason: 'quota_exceeded',
    has_subscription: false,
  },
  inbounds: [
    {
      id: 'in-1',
      kind: 'vless' as const,
      enabled: true,
      listen: '0.0.0.0',
      port: 443,
      default_port: 443,
      params: {
        public_key: 'pub-key-value',
        short_id: '55e1651e',
        server_name: 'www.apple.com',
        handshake_server: 'www.apple.com',
        handshake_port: 443,
        has_obfs: true,
        has_server_key: true,
      },
      certificate: null,
      requires_certificate: false,
      updated_at: T,
    },
    {
      id: 'in-2',
      kind: 'hysteria2' as const,
      enabled: false,
      listen: '0.0.0.0',
      port: 443,
      default_port: 443,
      params: { has_obfs: false, has_server_key: false },
      certificate: null,
      requires_certificate: true,
      updated_at: T,
    },
    {
      id: 'in-3',
      kind: 'trojan' as const,
      enabled: false,
      listen: '0.0.0.0',
      port: 443,
      default_port: 443,
      params: {},
      certificate: null,
      requires_certificate: true,
      updated_at: T,
    },
    {
      id: 'in-4',
      kind: 'shadowsocks' as const,
      enabled: false,
      listen: '0.0.0.0',
      port: 8388,
      default_port: 8388,
      params: {},
      certificate: null,
      requires_certificate: false,
      updated_at: T,
    },
  ],
  certificate: {
    id: 'cert-1',
    domain: 'vpn.example.com',
    issuer: "Let's Encrypt",
    expires_at: '2026-04-01T00:00:00Z',
    auto_renew: true,
    status: 'ready',
    source: 'acme',
    last_error: null,
    created_at: T,
    days_remaining: 90,
  },
  certificate2: {
    id: 'cert-2',
    domain: 'self.example.com',
    issuer: 'self-signed',
    expires_at: '2030-01-01T00:00:00Z',
    auto_renew: false,
    status: 'ready',
    source: 'self-signed',
    last_error: null,
    created_at: T,
    days_remaining: 1400,
  },
  stats: {
    role: 'server' as const,
    users: { total: 2, enabled: 1, online: 1, disabled: 1 },
    traffic: { today_up: 1024, today_down: 2048, session_up: 4096, session_down: 8192 },
    rates: { up: 128, down: 256 },
    engine: {
      running: true,
      revision: 'abc123',
      engine_version: '1.14.4-ostium.1',
      last_error: null,
      started_at: T,
    },
    connections: 3,
    online_users: [{ id: 'user-1', name: 'alice', up: 1024, down: 2048, online: true }],
    generated_at: T,
  },
  traffic: [
    { day: '2025-12-30', up: 1000, down: 2000 },
    { day: '2025-12-31', up: 1500, down: 2500 },
    { day: '2026-01-01', up: 2000, down: 3000 },
  ],
  alert: {
    id: 'alert-1',
    level: 'warning',
    code: 'certificate_expiring',
    message: 'certificate expires soon',
    acknowledged_at: null,
    created_at: T,
  },
  systemInfo: {
    app: { name: 'Ostium', version: '0.1.0', role: 'server' as const },
    host: {
      hostname: 'vps',
      platform: 'Linux-6.8',
      system: 'Linux',
      machine: 'x86_64',
      python: '3.13.5',
      uptime_seconds: 100000,
      pid: 123,
    },
    metrics: {
      cpu_percent: 12,
      load_1m: 0.5,
      memory_percent: 40,
      memory_used: 1024,
      memory_total: 4096,
      disk_percent: 55,
      disk_used: 10 * 1024 ** 3,
      disk_total: 20 * 1024 ** 3,
    },
    core: { running: true, pid: 123 },
    control_plane_uptime: 5000,
    server_host: 'vpn.example.com',
    mode: 'mixed' as const,
    proxy: {
      supported: true,
      platform: 'linux-gnome',
      enabled: false,
      host: '127.0.0.1',
      port: 7890,
    },
    tun: { enabled: false, interface: 'ostium0', mtu: 1500, stack: 'gvisor' },
  },
  profile: {
    id: 'profile-1',
    name: 'HK',
    kind: 'subscription',
    enabled: true,
    sort_order: 0,
    last_refresh_at: T,
    last_refresh_error: null,
    selected_endpoint: 'hk-0',
    subscription_url: 'https://sub.example.com/hk',
    endpoints: [
      {
        tag: 'hk-0',
        protocol: 'vless-reality',
        name: 'HK',
        server: 'vpn.example.com',
        port: 443,
        uuid: 'uuid',
        tls: { server_name: 'sni' },
      },
      {
        tag: 'jp-1',
        protocol: 'hysteria2',
        name: 'JP',
        server: 'jp.example.com',
        port: 8443,
        password: 'pw',
        tls: { server_name: 'jp' },
      },
    ],
    created_at: T,
  },
  rule: {
    id: 'rule-1',
    priority: 10,
    enabled: true,
    action: 'direct' as const,
    match: { domain_suffix: ['.cn'], ip_cidr: ['10.0.0.0/8'] },
    note: 'CN',
    updated_at: T,
  },
  rule2: {
    id: 'rule-2',
    priority: 20,
    enabled: false,
    action: 'block' as const,
    match: { domain_keyword: ['ads'] },
    note: 'ads',
    updated_at: T,
  },
  ruleSet: {
    id: 'set-1',
    name: 'ads',
    url: 'https://example.com/ads.srs',
    format: 'binary',
    enabled: true,
    path: '/var/lib/ostium/rulesets/ads.srs',
    sha256: 'abc',
    updated_at: T,
    last_error: null,
  },
  connection: {
    id: 'conn-1',
    metadata: {
      host: 'example.com',
      destinationIP: '1.2.3.4',
      network: 'tcp',
      processPath: '/usr/bin/curl',
    },
    upload: 100,
    download: 200,
    start: T,
    chains: ['proxy'],
    rule: 'MATCH',
    rulePayload: 'proxy',
  },
  job: {
    id: 'job-1',
    type: 'backup.create',
    status: 'succeeded',
    progress: 100,
    message: 'completed',
    result: { filename: 'ostium-backup.tar.gz' },
    error: null,
    cancel_requested: false,
    created_at: T,
    started_at: T,
    finished_at: T,
  },
  jobRunning: {
    id: 'job-2',
    type: 'acme.issue',
    status: 'running',
    progress: 40,
    message: 'working',
    result: null,
    error: null,
    cancel_requested: false,
    created_at: T,
    started_at: T,
    finished_at: null,
  },
  audit: {
    id: 'audit-1',
    actor: 'admin',
    action: 'user.created',
    target: 'alice',
    ip: '127.0.0.1',
    detail: { quota: 10 },
    created_at: T,
  },
  backup: {
    id: 'backup-1',
    filename: 'ostium-backup-20260101.tar.gz',
    size: 1024,
    sha256: 'abc',
    encrypted: true,
    created_at: T,
    exists: true,
  },
  settings: {
    general: {
      role: 'server' as const,
      version: '0.1.0',
      log_level: 'info',
      mixed_port: 7890,
      routing_mode: 'smart',
      mode: 'mixed' as const,
      tun_enabled: false,
      auto_connect: false,
      auto_reconnect: true,
      public_ui: false,
      domain: 'vpn.example.com',
      acme_email: 'admin@example.com',
      acme_staging: false,
    },
    security: {
      secure_cookies: true,
      trusted_hosts: ['localhost', 'vpn.example.com'],
      api_tokens: [{ id: 'tok-1', name: 'ci', scopes: ['read'], revoked: false }],
    },
    notifications: {
      webhook_url: 'https://hooks.example.com/x',
      has_webhook_secret: true,
      enabled: true,
    },
    maintenance: {
      update_channel: 'stable',
      audit_retention_days: 90,
      traffic_retention_days: 365,
      auto_backup: true,
    },
  },
  subscription: {
    token: 'sub-token',
    user: 'alice',
    formats: [
      { id: 'ostium', name: 'Ostium Profile v1', url: '/sub/sub-token?format=ostium' },
      { id: 'base64', name: 'Base64 URI list', url: '/sub/sub-token?format=base64' },
      { id: 'clash', name: 'Clash Meta YAML', url: '/sub/sub-token?format=clash' },
      { id: 'singbox', name: 'sing-box outbounds', url: '/sub/sub-token?format=singbox' },
    ],
    links: ['vless://uuid@vpn.example.com:443#HK'],
    qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
    expires_at: '2027-01-01T00:00:00Z',
    quota_bytes: 10 * 1024 ** 3,
    used_bytes: 2 * 1024 ** 3,
  },
}

export interface FetchOptions {
  mode?: 'happy' | 'empty' | 'error'
  role?: 'server' | 'client'
  overrides?: Record<string, unknown>
}

const EMPTY_LISTS = new Set([
  '/api/v1/users',
  '/api/v1/inbounds',
  '/api/v1/certificates',
  '/api/v1/alerts',
  '/api/v1/profiles',
  '/api/v1/rules',
  '/api/v1/rule-sets',
  '/api/v1/jobs',
  '/api/v1/audit',
  '/api/v1/backups',
  '/api/v1/subscriptions',
])

function jsonResponse(data: unknown, status = 200) {
  const body = JSON.stringify(data)
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => JSON.parse(body),
    text: async () => body,
  } as unknown as Response
}

function textResponse(text: string, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'text/plain' }),
    json: async () => {
      throw new Error('not json')
    },
    text: async () => text,
  } as unknown as Response
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

export function mockResponse(method: string, path: string, body: any, options: FetchOptions = {}) {
  const mode = options.mode || 'happy'
  const role = options.role || 'server'
  const overrides = options.overrides || {}
  const empty = mode === 'empty'

  for (const [key, value] of Object.entries(overrides)) {
    if (path === key || path.startsWith(`${key}?`)) return jsonResponse(clone(value))
  }

  if (mode === 'error' && !path.startsWith('/api/v1/auth/')) {
    return jsonResponse({ detail: 'simulated failure', code: 'simulated' }, 500)
  }

  if (path === '/api/v1/auth/csrf') return jsonResponse({ csrf_token: 'csrf' })
  if (path === '/api/v1/auth/status') {
    return jsonResponse({ ...fixtures.status, role, authenticated: true })
  }
  if (path === '/api/v1/auth/me') return jsonResponse({ ...fixtures.me, role })
  if (path === '/api/v1/auth/login') {
    return jsonResponse({ ok: true, must_change_password: false, totp_enabled: true })
  }
  if (path === '/api/v1/auth/logout') return jsonResponse({ ok: true })
  if (path === '/api/v1/auth/password') return jsonResponse({ ok: true })
  if (path === '/api/v1/auth/totp/start') {
    return jsonResponse({ secret: 'SECRET', uri: 'otpauth://totp/x', recovery_codes: ['a-b-c'] })
  }
  if (path === '/api/v1/auth/totp/confirm' || path === '/api/v1/auth/totp/disable') {
    return jsonResponse({ ok: true })
  }
  if (path === '/api/v1/setup') return jsonResponse({ ok: true, role, username: 'admin' })

  if (path === '/api/v1/stats/overview') {
    return jsonResponse({ ...fixtures.stats, role })
  }
  if (path === '/api/v1/stats/traffic') {
    return jsonResponse({ series: empty ? [] : clone(fixtures.traffic), days: 7, user_id: null })
  }
  if (path === '/api/v1/alerts') {
    return jsonResponse({ alerts: empty ? [] : [clone(fixtures.alert)] })
  }
  if (path === '/api/v1/inbounds') {
    return jsonResponse({ inbounds: empty ? [] : clone(fixtures.inbounds) })
  }
  if (path.startsWith('/api/v1/inbounds/') && method === 'PATCH') {
    const inbound = clone(
      fixtures.inbounds.find((item) => path.includes(item.kind)) || fixtures.inbounds[0],
    )
    return jsonResponse({ inbound: { ...inbound, ...body }, applied: true })
  }
  if (path.endsWith('/reality-keys')) {
    return jsonResponse({ params: { public_key: 'new-key' }, applied: true })
  }
  if (path === '/api/v1/certificates') {
    return jsonResponse({
      certificates: empty ? [] : [clone(fixtures.certificate), clone(fixtures.certificate2)],
    })
  }
  if (path === '/api/v1/certificates/issue') {
    return jsonResponse({ certificate: clone(fixtures.certificate), applied: true })
  }
  if (path === '/api/v1/certificates/upload') {
    return jsonResponse({ certificate: clone(fixtures.certificate), applied: true })
  }
  if (path.endsWith('/renew')) return jsonResponse({ job_id: 'job-1' })
  if (path.endsWith('/use')) return jsonResponse({ ok: true, applied: true })
  if (path.startsWith('/api/v1/certificates/') && method === 'DELETE') {
    return jsonResponse({ deleted: true })
  }

  if (path === '/api/v1/users') {
    if (method === 'POST') {
      return jsonResponse({
        user: { ...clone(fixtures.user), name: body?.name || 'new' },
        subscription: clone(fixtures.subscription),
        password_once: 'generated-password',
        applied: true,
      })
    }
    return jsonResponse({
      users: empty ? [] : [clone(fixtures.user), clone(fixtures.disabledUser)],
      total: empty ? 0 : 2,
    })
  }
  if (path === '/api/v1/users/bulk') return jsonResponse({ count: 2, action: body?.action })
  if (path.match(/^\/api\/v1\/users\/[^/]+\/usage$/)) {
    return jsonResponse({
      user: clone(fixtures.user),
      series: clone(fixtures.traffic),
      today: { up: 2000, down: 3000 },
    })
  }
  if (path.endsWith('/subscription/rotate')) {
    return jsonResponse({ ...clone(fixtures.subscription), token: 'rotated' })
  }
  if (path.endsWith('/subscription')) return jsonResponse(clone(fixtures.subscription))
  if (path.endsWith('/reset-usage'))
    return jsonResponse({ user: clone(fixtures.user), applied: true })
  if (path.endsWith('/rotate')) {
    return jsonResponse({ ok: true, subscription_token: 'rotated', applied: true })
  }
  if (path.endsWith('/export')) return jsonResponse({ format: 'ostium-profile' })
  if (path.match(/^\/api\/v1\/users\/[^/]+$/)) {
    if (method === 'DELETE') return jsonResponse({ deleted: true, applied: true })
    if (method === 'PATCH') {
      return jsonResponse({
        user: { ...clone(fixtures.user), ...body, id: path.split('/').pop() },
        applied: true,
      })
    }
    return jsonResponse({ user: clone(fixtures.user), pending_bytes: 0 })
  }
  if (path === '/api/v1/subscriptions') {
    return jsonResponse({
      subscriptions: empty
        ? []
        : [
            {
              user: clone(fixtures.user),
              has_token: true,
              status: 'active',
              links: ['vless://uuid@vpn.example.com:443#HK'],
            },
            {
              user: clone(fixtures.disabledUser),
              has_token: false,
              status: 'disabled',
              links: [],
            },
          ],
      base_url: 'https://vpn.example.com',
    })
  }

  if (path === '/api/v1/profiles') {
    if (method === 'POST') {
      return jsonResponse({ profile: clone(fixtures.profile), applied: true })
    }
    return jsonResponse({ profiles: empty ? [] : [clone(fixtures.profile)] })
  }
  if (path.match(/^\/api\/v1\/profiles\/[^/]+\/test$/)) {
    return jsonResponse({
      profile: 'HK',
      results: [
        { tag: 'hk-0', name: 'HK', delay_ms: 42, error: null },
        { tag: 'jp-1', name: 'JP', delay_ms: null, error: 'timeout' },
      ],
    })
  }
  if (path.endsWith('/export')) return jsonResponse({ endpoints: [] })
  if (path.endsWith('/refresh')) {
    return jsonResponse({ profile: clone(fixtures.profile), endpoints: 2, applied: true })
  }
  if (path.match(/^\/api\/v1\/profiles\/[^/]+$/)) {
    if (method === 'DELETE') return jsonResponse({ deleted: true, applied: true })
    return jsonResponse({ profile: { ...clone(fixtures.profile), ...body }, applied: true })
  }

  if (path === '/api/v1/rules') {
    if (method === 'POST') return jsonResponse({ rule: { ...clone(fixtures.rule), ...body } })
    return jsonResponse({ rules: empty ? [] : [clone(fixtures.rule), clone(fixtures.rule2)] })
  }
  if (path === '/api/v1/rules/reorder') return jsonResponse({ ok: true })
  if (path === '/api/v1/rules/test') {
    return jsonResponse({ matched: true, rule: clone(fixtures.rule), action: 'direct' })
  }
  if (path.startsWith('/api/v1/rules/')) {
    if (method === 'DELETE') return jsonResponse({ deleted: true })
    return jsonResponse({ rule: { ...clone(fixtures.rule), ...body } })
  }
  if (path === '/api/v1/rule-sets') {
    if (method === 'POST') return jsonResponse({ rule_set: clone(fixtures.ruleSet) })
    return jsonResponse({ rule_sets: empty ? [] : [clone(fixtures.ruleSet)] })
  }
  if (path.endsWith('/update'))
    return jsonResponse({ result: { updated: true }, rule_set: clone(fixtures.ruleSet) })
  if (path.startsWith('/api/v1/rule-sets/') && method === 'DELETE') {
    return jsonResponse({ deleted: true })
  }

  if (path === '/api/v1/connections') {
    return jsonResponse({
      connections: empty ? [] : [clone(fixtures.connection)],
      upload_total: 1000,
      download_total: 2000,
      unavailable: false,
    })
  }
  if (path.startsWith('/api/v1/connections/') && method === 'DELETE') {
    return jsonResponse({ closed: true })
  }

  if (path === '/api/v1/logs') {
    return jsonResponse({
      source: 'ostium',
      records: empty
        ? []
        : [
            {
              ts: T,
              level: 'info',
              message: 'control plane ready',
              context: {},
            },
            {
              ts: T,
              level: 'error',
              message: 'something failed',
              context: { error: 'boom' },
            },
          ],
      lines: empty ? [] : ['control plane ready', 'something failed'],
      unavailable: false,
    })
  }
  if (path === '/api/v1/logs/download') return textResponse('line one\nline two')
  if (path === '/api/v1/jobs')
    return jsonResponse({ jobs: empty ? [] : [clone(fixtures.job), clone(fixtures.jobRunning)] })
  if (path.startsWith('/api/v1/jobs/') && path.endsWith('/cancel')) {
    return jsonResponse({ cancelled: true })
  }
  if (path.startsWith('/api/v1/jobs/')) return jsonResponse({ job: clone(fixtures.job) })

  if (path === '/api/v1/audit') {
    return jsonResponse({ entries: empty ? [] : [clone(fixtures.audit)], limit: 200, offset: 0 })
  }
  if (path === '/api/v1/backups') {
    if (method === 'POST') return jsonResponse({ job_id: 'job-1' })
    return jsonResponse({ backups: empty ? [] : [clone(fixtures.backup)] })
  }
  if (path.endsWith('/restore'))
    return jsonResponse({ staged: true, restart_required: true, message: 'staged' })
  if (path.startsWith('/api/v1/backups/') && method === 'DELETE') {
    return jsonResponse({ deleted: true })
  }

  if (path === '/api/v1/settings') {
    const base = clone(fixtures.settings)
    if (method === 'PATCH') return jsonResponse({ ok: true, restart_required: true })
    return jsonResponse({ ...base, general: { ...base.general, role } })
  }
  if (path === '/api/v1/settings/public-ui') {
    return jsonResponse({ public_ui: true, restart_required: true, message: 'restart' })
  }
  if (path === '/api/v1/api-tokens') {
    if (method === 'POST')
      return jsonResponse({
        token: 'ost_token',
        id: 'tok-2',
        name: body?.name,
        scopes: body?.scopes,
      })
    return jsonResponse({ tokens: empty ? [] : clone(fixtures.settings.security.api_tokens) })
  }
  if (path.startsWith('/api/v1/api-tokens/') && method === 'DELETE') {
    return jsonResponse({ revoked: true })
  }

  if (path === '/api/v1/system/info') {
    return jsonResponse({
      ...clone(fixtures.systemInfo),
      app: { ...fixtures.systemInfo.app, role },
    })
  }
  if (path === '/api/v1/system/doctor') {
    return jsonResponse({
      checks: empty
        ? []
        : [
            { id: 'database', status: 'pass', message: 'SQLite is readable', fix: null },
            { id: 'core', status: 'warn', message: 'sing-box is stopped', fix: 'start it' },
            { id: 'engine', status: 'fail', message: 'binary missing', fix: 'install it' },
          ],
      generated_at: T,
    })
  }
  if (path === '/api/v1/system/services') {
    return jsonResponse({
      services: [
        { name: 'ostium.service', label: 'Control plane', running: true, detail: 'ok' },
        {
          name: 'ostium-core.service',
          label: 'Proxy core',
          running: true,
          reachable: true,
          detail: {},
        },
      ],
    })
  }
  if (path === '/api/v1/system/diagnostics') {
    return jsonResponse({ version: '0.1.0', role, checks: [], config: '{}', logs: [], system: {} })
  }
  if (path === '/api/v1/system/diagnostics/download') return textResponse('tar')
  if (path.endsWith('/restart')) return jsonResponse({ restarted: true, status: {} })
  if (path === '/api/v1/system/proxy') {
    return jsonResponse({
      supported: true,
      enabled: body?.enabled ?? true,
      platform: 'linux-gnome',
    })
  }
  if (path === '/api/v1/system/tun') {
    return jsonResponse({
      ok: true,
      message: body?.enabled ? 'TUN enabled' : 'TUN disabled',
      status: {},
    })
  }
  if (path === '/api/v1/system/mode') return jsonResponse({ mode: body?.mode })
  if (path === '/api/v1/system/connect') return jsonResponse({ connected: true, status: {} })
  if (path === '/api/v1/system/disconnect') return jsonResponse({ connected: false, status: {} })

  if (path === '/api/v1/alerts/ack') return jsonResponse({ acknowledged: true })
  if (path.startsWith('/api/v1/alerts/') && path.endsWith('/ack')) {
    return jsonResponse({ acknowledged: true })
  }

  if (EMPTY_LISTS.has(path)) return jsonResponse({})
  return jsonResponse({ ok: true })
}

export function installFetchMock(options: FetchOptions = {}) {
  const calls: Array<{ method: string; path: string; search: string; body: any }> = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input.toString()
    const url = new URL(raw, 'http://localhost')
    const method = (init?.method || 'GET').toUpperCase()
    let body: any = undefined
    if (typeof init?.body === 'string') {
      try {
        body = JSON.parse(init.body)
      } catch {
        body = init.body
      }
    }
    calls.push({ method, path: url.pathname, search: url.search, body })
    return mockResponse(method, url.pathname, body, options)
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

export async function settle(times = 5) {
  for (let index = 0; index < times; index += 1) {
    await flushPromises()
    await nextTick()
  }
}

export async function mountPage(
  component: any,
  props: Record<string, unknown> = {},
  prepare?: (pinia: ReturnType<typeof createPinia>) => void | Promise<void>,
) {
  const pinia = createPinia()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  if (prepare) await prepare(pinia)

  const Page = defineComponent({
    render: () => h(component, props),
  })
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
                      default: () => h(NMessageProvider, null, { default: () => h(Page) }),
                    }),
                }),
            }),
        },
      ),
  })

  const wrapper = mount(Host, {
    attachTo: document.body,
    global: {
      plugins: [pinia, i18n, router],
    },
  })
  await settle()
  return { wrapper, router, pinia }
}

export async function clickAllButtons(rounds = 2) {
  for (let round = 0; round < rounds; round += 1) {
    const buttons = Array.from(document.querySelectorAll('button')).filter(
      (button) => !(button as HTMLButtonElement).disabled,
    )
    for (const button of buttons.slice(0, 80)) {
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await nextTick()
    }
    await settle(2)
  }
}

export function cleanupPage() {
  document.body.innerHTML = ''
}

export async function clickByText(text: string, selector = 'button') {
  const nodes = Array.from(document.querySelectorAll(selector)) as HTMLElement[]
  const match = nodes.find((node) => (node.textContent || '').trim().includes(text))
  if (match) {
    match.click()
    await settle(2)
    return true
  }
  return false
}

export async function clickLastByText(text: string, selector = 'button') {
  const nodes = Array.from(document.querySelectorAll(selector)) as HTMLElement[]
  const matches = nodes.filter((node) => (node.textContent || '').trim().includes(text))
  const match = matches[matches.length - 1]
  if (match) {
    match.click()
    await settle(2)
    return true
  }
  return false
}

export async function clickSelector(selector: string, index = 0) {
  const nodes = Array.from(document.querySelectorAll(selector)) as HTMLElement[]
  nodes[index]?.click()
  await settle(2)
}

export async function fillInputs(values: Record<string, string> = {}) {
  const inputs = Array.from(
    document.querySelectorAll('input:not([type="checkbox"]):not([type="radio"]), textarea'),
  ) as Array<HTMLInputElement | HTMLTextAreaElement>
  const hasSelectors = Object.keys(values).length > 0
  for (const input of inputs) {
    const placeholder = input.getAttribute('placeholder') || ''
    const selected = values[placeholder] || values[input.getAttribute('data-testid') || '']
    if (hasSelectors && !selected) continue
    const value = selected || (input.type === 'number' ? '10' : 'Test value')
    const setter = Object.getOwnPropertyDescriptor(
      input instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype,
      'value',
    )?.set
    setter?.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
    await nextTick()
  }
  await settle(1)
}

export { T as FIXED_TIME }
