/**
 * HTTP client for the CareerIQ API.
 *
 * Built on `fetch` rather than axios: the only things axios would add here are
 * interceptors and JSON parsing, both of which are a few lines below, and it
 * would ship ~13 kB to every user for the privilege.
 */

import { ErrorCode, type ApiErrorBody, type FieldError } from '@/types/api'
import type { TokenPair } from '@/types/auth'
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setAccessToken,
  setRefreshToken,
} from './tokenStorage'

const API_BASE = '/api/v1'

/** A failed request, carrying the backend's stable error code. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>
  readonly correlationId: string | undefined

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    correlationId?: string,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.correlationId = correlationId
  }

  /** Field errors from a 422, for rendering next to the offending inputs. */
  get fieldErrors(): FieldError[] {
    const fields = this.details.fields
    return Array.isArray(fields) ? (fields as FieldError[]) : []
  }

  fieldError(name: string): string | undefined {
    return this.fieldErrors.find((f) => f.field === name)?.message
  }
}

/**
 * Called when the session is unrecoverable and the user must sign in again.
 * The auth provider registers a handler; keeping it a callback means this
 * module stays free of React and router imports and remains unit-testable.
 */
type UnauthenticatedHandler = () => void
let onUnauthenticated: UnauthenticatedHandler = () => {}

export function setUnauthenticatedHandler(handler: UnauthenticatedHandler): void {
  onUnauthenticated = handler
}

/**
 * In-flight refresh, shared by every request that hits a 401 concurrently.
 *
 * This is a correctness requirement, not a performance tweak. Refresh tokens
 * rotate on use and the backend treats a second use of a consumed token as
 * theft, revoking the entire family (US-1.3 AC2). If a dashboard fired three
 * requests that all 401'd and each called refresh independently, the first
 * would succeed and the other two would be reuse — logging the user out for
 * doing nothing wrong. Sharing one promise means exactly one refresh happens.
 */
/**
 * Three outcomes, not two.
 *
 * A boolean cannot express the difference between "the server rejected this
 * token" and "we could not reach the server", and the two demand opposite
 * responses: the first must end the session, the second must preserve it. A
 * boolean here caused exactly that bug — an offline blip logged the user out.
 */
type RefreshResult = 'refreshed' | 'rejected' | 'unreachable'

let refreshInFlight: Promise<RefreshResult> | null = null

async function performRefresh(): Promise<RefreshResult> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return 'rejected'

  try {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })

    if (!response.ok) {
      // Expired, revoked, or reuse detected. All terminal — no second attempt
      // could succeed, so the session is genuinely over.
      return 'rejected'
    }

    const tokens = (await response.json()) as TokenPair
    setAccessToken(tokens.access_token)
    setRefreshToken(tokens.refresh_token)
    return 'refreshed'
  } catch {
    // The session may be perfectly valid and the user merely offline. Tokens
    // are kept so the next attempt, once connectivity returns, can succeed.
    return 'unreachable'
  }
}

function refreshAccessToken(): Promise<RefreshResult> {
  refreshInFlight ??= performRefresh().finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}

async function parseError(response: Response): Promise<ApiError> {
  let body: ApiErrorBody | undefined
  try {
    body = (await response.json()) as ApiErrorBody
  } catch {
    // A proxy timeout or gateway error returns HTML, not our envelope.
  }

  const error = body?.error
  return new ApiError(
    response.status,
    error?.code ?? `HTTP_${response.status}`,
    error?.message ?? response.statusText ?? 'Request failed.',
    error?.details ?? {},
    error?.correlation_id,
  )
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  /** Skip the Authorization header — used by login, register and refresh. */
  skipAuth?: boolean
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
  isRetry = false,
): Promise<T> {
  const { body, skipAuth = false, headers, ...init } = options

  const requestHeaders = new Headers(headers)
  if (body !== undefined) requestHeaders.set('Content-Type', 'application/json')

  const accessToken = getAccessToken()
  if (!skipAuth && accessToken) {
    requestHeaders.set('Authorization', `Bearer ${accessToken}`)
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: requestHeaders,
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
  } catch {
    throw new ApiError(
      0,
      ErrorCode.NetworkError,
      'Could not reach the server. Check your connection and try again.',
    )
  }

  if (response.status === 401 && !skipAuth && !isRetry) {
    // One retry only. `isRetry` guards against an infinite loop when the
    // refresh succeeds but the endpoint keeps returning 401 for another reason
    // — a deactivated account, for instance.
    const result = await refreshAccessToken()

    if (result === 'refreshed') return request<T>(path, options, true)

    if (result === 'rejected') {
      // Only a server rejection ends the session. An 'unreachable' result falls
      // through with tokens intact, and the caller sees the original 401.
      clearTokens()
      onUnauthenticated()
    }
  }

  if (!response.ok) throw await parseError(response)

  // 204, and any other genuinely empty body.
  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T
  }

  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'GET' }),

  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'POST', body }),

  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PATCH', body }),

  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PUT', body }),

  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'DELETE' }),
}

/** Test-only: reset the shared refresh promise between cases. */
export function __resetRefreshState(): void {
  refreshInFlight = null
}
