export interface ApiProblem {
  type?: string
  title?: string
  status?: number
  detail?: string
  code?: string
  request_id?: string
  errors?: unknown
}

export class ApiError extends Error {
  status: number
  code: string
  problem: ApiProblem

  constructor(status: number, problem: ApiProblem) {
    super(problem.detail || problem.title || `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = problem.code || 'api_error'
    this.problem = problem
  }
}

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|; )ostium_csrf=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

let csrfReady: Promise<void> | null = null

export async function ensureCsrf(): Promise<void> {
  if (csrfReady) return csrfReady
  csrfReady = (async () => {
    if (!csrfToken()) {
      await fetch('/api/v1/auth/csrf', { credentials: 'same-origin' })
    }
  })().finally(() => {
    csrfReady = null
  })
  return csrfReady
}

const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  init?: RequestInit,
): Promise<T> {
  if (MUTATING.has(method)) await ensureCsrf()
  const headers = new Headers(init?.headers)
  headers.set('Accept', 'application/json')
  if (body !== undefined && !(body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  if (MUTATING.has(method)) {
    const token = csrfToken()
    if (token) headers.set('X-CSRF-Token', token)
  }
  const response = await fetch(path, {
    ...init,
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
  })
  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json')
    ? await response.json().catch(() => ({}))
    : await response.text()
  if (!response.ok) {
    if (typeof payload === 'string') {
      throw new ApiError(response.status, { detail: payload, code: 'http_error' })
    }
    throw new ApiError(response.status, payload as ApiProblem)
  }
  return payload as T
}

export const http = {
  get: <T>(path: string, init?: RequestInit) => request<T>('GET', path, undefined, init),
  post: <T>(path: string, body?: unknown, init?: RequestInit) =>
    request<T>('POST', path, body, init),
  patch: <T>(path: string, body?: unknown, init?: RequestInit) =>
    request<T>('PATCH', path, body, init),
  put: <T>(path: string, body?: unknown, init?: RequestInit) => request<T>('PUT', path, body, init),
  delete: <T>(path: string, init?: RequestInit) => request<T>('DELETE', path, undefined, init),
}
