export type Role = 'server' | 'client'
export type ThemeMode = 'dark' | 'light' | 'system'
export type ConnectionMode = 'mixed' | 'system_proxy' | 'tun'

export interface AuthStatus {
  initialized: boolean
  has_admin: boolean
  authenticated: boolean
  must_change_password: boolean
  totp_enabled: boolean
  role: Role
  version: string
  public_ui: boolean
}

export interface Me {
  id: string
  username: string
  must_change_password: boolean
  totp_enabled: boolean
  recovery_codes_remaining: number
  last_login_at: string | null
  role: Role
}

export interface User {
  id: string
  name: string
  enabled: boolean
  uuid: string
  expires_at: string | null
  quota_bytes: number
  quota_cycle: 'total' | 'monthly'
  cycle_started_at: string | null
  used_bytes: number
  note: string
  status: string
  online: boolean
  last_seen_at: string | null
  created_at: string
  disabled_reason: string | null
  has_subscription: boolean
}

export interface InboundParams {
  public_key?: string | null
  short_id?: string | null
  server_name?: string | null
  handshake_server?: string | null
  handshake_port?: number | null
  has_obfs?: boolean
  has_server_key?: boolean
}

export interface Inbound {
  id: string
  kind: 'vless' | 'hysteria2' | 'trojan' | 'shadowsocks'
  enabled: boolean
  listen: string
  port: number
  default_port: number
  params: InboundParams
  certificate: Certificate | null
  requires_certificate: boolean
  updated_at: string | null
}

export interface Certificate {
  id: string
  domain: string
  issuer: string | null
  expires_at: string | null
  auto_renew: boolean
  status: string
  source: string
  last_error: string | null
  created_at: string | null
  days_remaining: number | null
}

export interface SubscriptionFormat {
  id: string
  name: string
  url: string
}

export interface SubscriptionPayload {
  token: string
  user: string
  formats: SubscriptionFormat[]
  links: string[]
  qr_svg: string
  expires_at: string | null
  quota_bytes: number
  used_bytes: number
}

export interface Endpoint {
  tag: string
  protocol: string
  name: string
  server: string
  port: number
  uuid?: string | null
  password?: string | null
  flow?: string
  method?: string
  tls: Record<string, unknown>
}

export interface Profile {
  id: string
  name: string
  kind: string
  enabled: boolean
  sort_order: number
  last_refresh_at: string | null
  last_refresh_error: string | null
  selected_endpoint: string | null
  subscription_url: string | null
  endpoints: Endpoint[]
  created_at: string
}

export interface Rule {
  id: string
  priority: number
  enabled: boolean
  action: 'proxy' | 'direct' | 'block'
  match: Record<string, unknown>
  note: string
  updated_at: string | null
}

export interface RuleSet {
  id: string
  name: string
  url: string
  format: string
  enabled: boolean
  path: string | null
  sha256: string | null
  updated_at: string | null
  last_error: string | null
}

export interface StatsOverview {
  role: Role
  users: { total: number; enabled: number; online: number; disabled: number }
  traffic: { today_up: number; today_down: number; session_up: number; session_down: number }
  rates: { up: number; down: number }
  engine: {
    running: boolean
    revision: string | null
    engine_version: string | null
    last_error: string | null
    started_at: string | null
  }
  connections: number
  online_users: Array<{ id: string; name: string; up: number; down: number; online: boolean }>
  generated_at: string
}

export interface TrafficPoint {
  day: string
  up: number
  down: number
}

export interface ConnectionEntry {
  id: string
  metadata: Record<string, unknown>
  upload: number
  download: number
  start: string
  chains: string[]
  rule?: string
  rulePayload?: string
}

export interface Job {
  id: string
  type: string
  status: string
  progress: number
  message: string
  result: Record<string, unknown> | null
  error: string | null
  cancel_requested: boolean
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface Alert {
  id: string
  level: string
  code: string
  message: string
  acknowledged_at: string | null
  created_at: string
}

export interface AuditEntry {
  id: string
  actor: string
  action: string
  target: string | null
  ip: string | null
  detail: Record<string, unknown>
  created_at: string
}

export interface Backup {
  id: string
  filename: string
  size: number
  sha256: string
  encrypted: boolean
  created_at: string
  exists: boolean
}

export interface DoctorCheck {
  id: string
  status: 'pass' | 'warn' | 'fail'
  message: string
  fix: string | null
}

export interface SystemInfo {
  app: { name: string; version: string; role: Role }
  host: {
    hostname: string
    platform: string
    system: string
    machine: string
    python: string
    uptime_seconds: number
    pid: number
  }
  metrics: {
    cpu_percent: number
    load_1m: number | null
    memory_percent: number
    memory_used: number
    memory_total: number
    disk_percent: number
    disk_used: number
    disk_total: number
  }
  core: Record<string, unknown>
  control_plane_uptime: number
  server_host: string | null
  mode: ConnectionMode
  proxy: {
    supported: boolean
    platform: string
    enabled: boolean
    host: string
    port: number
  }
  tun: {
    enabled: boolean
    interface: string
    mtu: number
    stack: string
  }
}

export interface ServiceStatus {
  name: string
  label: string
  running: boolean
  reachable?: boolean
  detail: unknown
}

export interface AppSettings {
  general: {
    role: Role
    version: string
    log_level: string
    mixed_port: number
    routing_mode: string
    mode: ConnectionMode
    tun_enabled: boolean
    public_ui: boolean
    domain: string | null
    acme_email: string | null
    acme_staging: boolean
  }
  security: {
    secure_cookies: boolean
    trusted_hosts: string[]
    api_tokens: Array<Record<string, unknown>>
  }
  notifications: { webhook_url: string | null; has_webhook_secret: boolean; enabled: boolean }
  maintenance: {
    update_channel: string
    audit_retention_days: number
    traffic_retention_days: number
    auto_backup: boolean
  }
}

export interface LogRecord {
  ts: string
  level: string
  message: string
  context: Record<string, string>
}

export interface EventFrame {
  type: string
  ts: string
  data: Record<string, unknown>
}
