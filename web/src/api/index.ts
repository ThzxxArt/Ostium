import { http } from './client'
import type {
  Alert,
  AppSettings,
  AuditEntry,
  AuthStatus,
  Backup,
  Certificate,
  ConnectionEntry,
  DoctorCheck,
  Inbound,
  Job,
  LogRecord,
  Me,
  Profile,
  Rule,
  RuleSet,
  ServiceStatus,
  StatsOverview,
  SubscriptionPayload,
  SystemInfo,
  TrafficPoint,
  User,
} from './types'

const v1 = '/api/v1'

export const api = {
  auth: {
    status: () => http.get<AuthStatus>(`${v1}/auth/status`),
    csrf: () => http.get<{ csrf_token: string }>(`${v1}/auth/csrf`),
    login: (username: string, password: string, totp?: string, recoveryCode?: string) =>
      http.post<{ ok: boolean; must_change_password: boolean; totp_enabled: boolean }>(
        `${v1}/auth/login`,
        { username, password, totp, recovery_code: recoveryCode },
      ),
    logout: () => http.post<{ ok: boolean }>(`${v1}/auth/logout`),
    me: () => http.get<Me>(`${v1}/auth/me`),
    setup: (payload: {
      role: string
      username: string
      password: string
      domain?: string
      public_ui?: boolean
      lines?: 'reality' | 'later'
    }) => http.post<{ ok: boolean; role: string; username: string }>(`${v1}/setup`, payload),
    changePassword: (current_password: string, new_password: string) =>
      http.post<{ ok: boolean; sessions_revoked: number }>(`${v1}/auth/password`, {
        current_password,
        new_password,
      }),
    totpStart: () =>
      http.post<{ secret: string; uri: string; recovery_codes: string[] }>(`${v1}/auth/totp/start`),
    totpConfirm: (code: string) => http.post<{ ok: boolean }>(`${v1}/auth/totp/confirm`, { code }),
    totpCancel: () => http.post<{ ok: boolean }>(`${v1}/auth/totp/cancel`),
    totpDisable: (password: string) =>
      http.post<{ ok: boolean }>(`${v1}/auth/totp/disable`, { password }),
  },
  inbounds: {
    list: () => http.get<{ inbounds: Inbound[] }>(`${v1}/inbounds`),
    update: (kind: string, payload: Record<string, unknown>) =>
      http.patch<{ inbound: Inbound; applied: boolean; warning?: string }>(
        `${v1}/inbounds/${kind}`,
        payload,
      ),
    rotateReality: (kind = 'vless') =>
      http.post<{ params: Record<string, string>; applied: boolean; warning?: string }>(
        `${v1}/inbounds/${kind}/reality-keys`,
      ),
  },
  users: {
    list: () => http.get<{ users: User[]; total: number }>(`${v1}/users`),
    create: (payload: Record<string, unknown>) =>
      http.post<{
        user: User
        subscription: SubscriptionPayload
        password_once: string
        applied: boolean
        warning?: string
      }>(`${v1}/users`, payload),
    get: (id: string) => http.get<{ user: User; pending_bytes: number }>(`${v1}/users/${id}`),
    update: (id: string, payload: Record<string, unknown>) =>
      http.patch<{ user: User; applied: boolean; warning?: string }>(`${v1}/users/${id}`, payload),
    remove: (id: string) =>
      http.delete<{ deleted: boolean; applied: boolean; warning?: string }>(`${v1}/users/${id}`),
    rotate: (id: string, rotateSubscription = false) =>
      http.post<{ ok: boolean; subscription_token?: string; applied: boolean; warning?: string }>(
        `${v1}/users/${id}/rotate`,
        { rotate_subscription: rotateSubscription },
      ),
    resetUsage: (id: string) =>
      http.post<{ user: User; applied: boolean; warning?: string }>(
        `${v1}/users/${id}/reset-usage`,
      ),
    usage: (id: string, days = 30) =>
      http.get<{
        user: User
        series: TrafficPoint[]
        today: TrafficPoint | Record<string, number>
      }>(`${v1}/users/${id}/usage?days=${days}`),
    subscription: (id: string, reveal = false) =>
      http.get<SubscriptionPayload>(`${v1}/users/${id}/subscription?reveal=${reveal}`),
    rotateSubscription: (id: string) =>
      http.post<SubscriptionPayload>(`${v1}/users/${id}/subscription/rotate`),
    export: (id: string) => http.get<Record<string, unknown>>(`${v1}/users/${id}/export`),
    bulk: (action: string, ids: string[]) =>
      http.post<{
        count: number
        action: string
        applied?: boolean
        warning?: string
        exports?: Array<Record<string, unknown>>
      }>(`${v1}/users/bulk`, {
        action,
        ids,
      }),
  },
  subscriptions: {
    overview: () =>
      http.get<{
        subscriptions: Array<{ user: User; has_token: boolean; status: string; links: string[] }>
        base_url: string
      }>(`${v1}/subscriptions`),
  },
  profiles: {
    list: () =>
      http.get<{ profiles: Profile[]; active_profile_id: string | null }>(`${v1}/profiles`),
    create: (payload: { name: string; text?: string; url?: string }) =>
      http.post<{ profile: Profile; applied: boolean; warning?: string }>(
        `${v1}/profiles`,
        payload,
      ),
    update: (id: string, payload: Record<string, unknown>) =>
      http.patch<{ profile: Profile; applied: boolean; warning?: string }>(
        `${v1}/profiles/${id}`,
        payload,
      ),
    activate: (id: string) =>
      http.post<{ profile: Profile; applied: boolean; warning?: string }>(
        `${v1}/profiles/${id}/activate`,
      ),
    reorder: (ids: string[]) =>
      http.post<{ ok: boolean; applied?: boolean; warning?: string }>(`${v1}/profiles/reorder`, {
        ids,
      }),
    remove: (id: string) =>
      http.delete<{ deleted: boolean; applied: boolean; warning?: string }>(`${v1}/profiles/${id}`),
    refresh: (id: string) =>
      http.post<{ profile: Profile; endpoints: number; applied: boolean; warning?: string }>(
        `${v1}/profiles/${id}/refresh`,
      ),
    export: (id: string) => http.get<Record<string, unknown>>(`${v1}/profiles/${id}/export`),
    test: (id: string) =>
      http.get<{
        profile: string
        results: Array<{ tag: string; name: string; delay_ms: number | null; error: string | null }>
      }>(`${v1}/profiles/${id}/test`),
  },
  rules: {
    list: () => http.get<{ rules: Rule[] }>(`${v1}/rules`),
    create: (payload: Record<string, unknown>) =>
      http.post<{ rule: Rule; applied?: boolean; warning?: string }>(`${v1}/rules`, payload),
    update: (id: string, payload: Record<string, unknown>) =>
      http.patch<{ rule: Rule; applied?: boolean; warning?: string }>(`${v1}/rules/${id}`, payload),
    remove: (id: string) =>
      http.delete<{ deleted: boolean; applied?: boolean; warning?: string }>(`${v1}/rules/${id}`),
    reorder: (ids: string[]) =>
      http.post<{ ok: boolean; applied?: boolean; warning?: string }>(`${v1}/rules/reorder`, {
        ids,
      }),
    test: (payload: Record<string, unknown>) =>
      http.post<{ matched: boolean; rule?: Rule; action?: string }>(`${v1}/rules/test`, payload),
    ruleSets: () => http.get<{ rule_sets: RuleSet[] }>(`${v1}/rule-sets`),
    addRuleSet: (payload: Record<string, unknown>) =>
      http.post<{ rule_set: RuleSet }>(`${v1}/rule-sets`, payload),
    updateRuleSet: (id: string) =>
      http.post<{
        result: Record<string, unknown>
        rule_set: RuleSet
        applied?: boolean
        warning?: string
      }>(`${v1}/rule-sets/${id}/update`),
    removeRuleSet: (id: string) =>
      http.delete<{ deleted: boolean; applied?: boolean; warning?: string }>(
        `${v1}/rule-sets/${id}`,
      ),
  },
  stats: {
    overview: () => http.get<StatsOverview>(`${v1}/stats/overview`),
    traffic: (days = 30, userId?: string) =>
      http.get<{ series: TrafficPoint[]; days: number; user_id: string | null }>(
        `${v1}/stats/traffic?days=${days}${userId ? `&user_id=${userId}` : ''}`,
      ),
    connections: (search?: string) =>
      http.get<{
        connections: ConnectionEntry[]
        upload_total: number
        download_total: number
        unavailable: boolean
      }>(`${v1}/connections${search ? `?search=${encodeURIComponent(search)}` : ''}`),
    closeConnection: (id: string) => http.delete<{ closed: boolean }>(`${v1}/connections/${id}`),
    closeAll: () => http.delete<{ closed: boolean }>(`${v1}/connections`),
  },
  logs: {
    get: (source = 'ostium', level?: string, search?: string, limit = 500) =>
      http.get<{
        source: string
        records?: LogRecord[]
        lines: string[]
        error?: string
        unavailable?: boolean
      }>(
        `${v1}/logs?source=${source}&limit=${limit}${level ? `&level=${level}` : ''}${
          search ? `&search=${encodeURIComponent(search)}` : ''
        }`,
      ),
    downloadUrl: (source = 'ostium') => `${v1}/logs/download?source=${source}`,
  },
  certificates: {
    list: () => http.get<{ certificates: Certificate[] }>(`${v1}/certificates`),
    issue: (
      domain: string,
      method: 'acme' | 'self-signed' = 'acme',
      autoRenew = true,
      options: { staging?: boolean; email?: string } = {},
    ) =>
      http.post<{
        certificate?: Certificate
        job_id?: string
        applied?: boolean
        warning?: string
      }>(`${v1}/certificates/issue`, {
        domain,
        method,
        auto_renew: autoRenew,
        staging: options.staging,
        email: options.email,
      }),
    upload: (payload: {
      domain: string
      cert_pem: string
      key_pem: string
      auto_renew?: boolean
    }) =>
      http.post<{ certificate: Certificate; applied: boolean; warning?: string }>(
        `${v1}/certificates/upload`,
        payload,
      ),
    renew: (id: string) => http.post<{ job_id: string }>(`${v1}/certificates/${id}/renew`),
    use: (id: string, kinds: string[]) =>
      http.post<{ ok: boolean; applied: boolean; warning?: string }>(
        `${v1}/certificates/${id}/use`,
        { kinds },
      ),
    remove: (id: string) =>
      http.delete<{ deleted: boolean; applied?: boolean; warning?: string }>(
        `${v1}/certificates/${id}`,
      ),
  },
  jobs: {
    list: (limit = 100) => http.get<{ jobs: Job[] }>(`${v1}/jobs?limit=${limit}`),
    get: (id: string) => http.get<{ job: Job }>(`${v1}/jobs/${id}`),
    cancel: (id: string) => http.post<{ cancelled: boolean }>(`${v1}/jobs/${id}/cancel`),
  },
  system: {
    info: () => http.get<SystemInfo>(`${v1}/system/info`),
    doctor: () => http.get<{ checks: DoctorCheck[]; generated_at: string }>(`${v1}/system/doctor`),
    proxy: (enabled: boolean) =>
      http.post<{ supported: boolean; enabled: boolean; platform: string }>(`${v1}/system/proxy`, {
        enabled,
      }),
    tun: (enabled: boolean) =>
      http.post<{ ok: boolean; message: string; status: Record<string, unknown> }>(
        `${v1}/system/tun`,
        {
          enabled,
        },
      ),
    mode: (mode: string) => http.post<{ mode: string }>(`${v1}/system/mode`, { mode }),
    connect: () =>
      http.post<{ connected: boolean; status: Record<string, unknown> }>(`${v1}/system/connect`),
    disconnect: () =>
      http.post<{ connected: boolean; status: Record<string, unknown> }>(`${v1}/system/disconnect`),
    services: () => http.get<{ services: ServiceStatus[] }>(`${v1}/system/services`),
    restart: (name: string) =>
      http.post<{ restarted: boolean; status?: Record<string, unknown> }>(
        `${v1}/system/services/${name}/restart`,
      ),
    diagnostics: () => http.get<Record<string, unknown>>(`${v1}/system/diagnostics`),
    diagnosticsUrl: () => `${v1}/system/diagnostics/download`,
  },
  settings: {
    get: () => http.get<AppSettings>(`${v1}/settings`),
    update: (payload: Record<string, unknown>) =>
      http.patch<{
        ok: boolean
        restart_required?: boolean
        applied?: boolean
        warning?: string
      }>(`${v1}/settings`, payload),
    publicUi: (enabled: boolean, domain?: string) =>
      http.post<{ public_ui: boolean; restart_required: boolean; message: string }>(
        `${v1}/settings/public-ui`,
        { enabled, domain },
      ),
    tokens: () => http.get<{ tokens: Array<Record<string, unknown>> }>(`${v1}/api-tokens`),
    createToken: (name: string, scopes: string[]) =>
      http.post<{ token: string; id: string; name: string; scopes: string[] }>(`${v1}/api-tokens`, {
        name,
        scopes,
      }),
    revokeToken: (id: string) => http.delete<{ revoked: boolean }>(`${v1}/api-tokens/${id}`),
  },
  backups: {
    list: () => http.get<{ backups: Backup[] }>(`${v1}/backups`),
    create: (password?: string, acknowledgePlaintext = false) =>
      http.post<{ job_id: string }>(`${v1}/backups`, {
        password,
        acknowledge_plaintext: acknowledgePlaintext,
      }),
    restore: (id: string, password?: string) =>
      http.post<{ staged: boolean; restart_required: boolean; message: string }>(
        `${v1}/backups/${id}/restore`,
        { password },
      ),
    remove: (id: string) => http.delete<{ deleted: boolean }>(`${v1}/backups/${id}`),
  },
  alerts: {
    list: (includeAcknowledged = false) =>
      http.get<{ alerts: Alert[] }>(`${v1}/alerts?include_acknowledged=${includeAcknowledged}`),
    ack: (id: string) => http.post<{ acknowledged: boolean }>(`${v1}/alerts/${id}/ack`),
  },
  audit: {
    list: (limit = 200, offset = 0) =>
      http.get<{ entries: AuditEntry[]; limit: number; offset: number }>(
        `${v1}/audit?limit=${limit}&offset=${offset}`,
      ),
  },
}
