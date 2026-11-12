export function formatBytes(value: number | null | undefined, digits = 1): string {
  const size = Number(value || 0)
  if (!Number.isFinite(size) || size <= 0) return '0 B'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']
  const index = Math.min(units.length - 1, Math.floor(Math.log(size) / Math.log(1024)))
  const amount = size / 1024 ** index
  return `${amount.toFixed(index === 0 ? 0 : digits)} ${units[index]}`
}

export function formatRate(value: number | null | undefined): string {
  return `${formatBytes(value || 0)}/s`
}

export function formatPercent(value: number | null | undefined): string {
  return `${Math.round(Number(value || 0))}%`
}

export function formatDuration(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.floor(Number(seconds || 0)))
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m`
  return `${total}s`
}

export function formatDate(value: string | null | undefined, locale = 'zh-CN'): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function formatDay(value: string, locale = 'zh-CN'): string {
  const date = new Date(value)
  return new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric' }).format(date)
}

export function relativeTime(value: string | null | undefined, locale = 'zh-CN'): string {
  if (!value) return '—'
  const then = new Date(value).getTime()
  if (Number.isNaN(then)) return '—'
  const diff = Math.round((then - Date.now()) / 1000)
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['year', 31536000],
    ['month', 2592000],
    ['day', 86400],
    ['hour', 3600],
    ['minute', 60],
    ['second', 1],
  ]
  for (const [unit, size] of units) {
    if (Math.abs(diff) >= size || unit === 'second') {
      return formatter.format(Math.round(diff / size), unit)
    }
  }
  return '—'
}

export function percentOf(used: number, total: number): number {
  if (!total) return 0
  return Math.max(0, Math.min(100, (used / total) * 100))
}

export function initials(name: string): string {
  const trimmed = name.trim()
  if (!trimmed) return '?'
  const parts = trimmed.split(/[\s._-]+/)
  if (parts.length > 1) return (parts[0][0] + parts[1][0]).toUpperCase()
  return trimmed.slice(0, 2).toUpperCase()
}

export function statusTone(status: string): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
  switch (status) {
    case 'online':
    case 'active':
    case 'connected':
    case 'running':
    case 'ready':
    case 'succeeded':
    case 'pass':
      return 'success'
    case 'connecting':
    case 'pending':
    case 'queued':
    case 'degraded':
    case 'warn':
    case 'warning':
      return 'warning'
    case 'expired':
    case 'quota_exceeded':
    case 'error':
    case 'failed':
    case 'fail':
    case 'interrupted':
      return 'danger'
    case 'disabled':
    case 'offline':
    case 'stopped':
    case 'cancelled':
      return 'neutral'
    default:
      return 'info'
  }
}
