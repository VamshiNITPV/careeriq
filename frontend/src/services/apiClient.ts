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
  currentSessionEpoch,
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
/** `reason` is passed on only when the server said why. */
type UnauthenticatedHandler = (reason?: 'idle') => void
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

/** Set by the rejecting refresh, read by the 401 handler immediately after. */
let lastRejectionReason: 'idle' | undefined

async function performRefresh(): Promise<RefreshResult> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return 'rejected'

  // Captured before the request. If the session ends while this is in
  // flight, the tokens that come back belong to a session that is over.
  const epoch = currentSessionEpoch()

  try {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })

    if (!response.ok) {
      // Expired, revoked, reused, or idle. All terminal — no second attempt
      // could succeed, so the session is genuinely over. The body is read only
      // to tell the idle case apart, because that is the one the login page can
      // explain; anything unreadable simply carries no reason.
      let reason: 'idle' | undefined
      try {
        const body = (await response.json()) as { error?: { code?: string } }
        if (body.error?.code === ErrorCode.SessionIdleTimeout) reason = 'idle'
      } catch {
        // Not JSON, or already consumed. No reason to report.
      }
      lastRejectionReason = reason
      return 'rejected'
    }

    // Signed out while we were waiting. Writing these would resurrect the
            // session on the next page load.
    if (epoch !== currentSessionEpoch()) return 'rejected'

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
  /**
   * How to read a successful body. Defaults to 'json'.
   *
   * Carried on the options object rather than expressed as a separate
   * `requestBlob()` function, and that is load-bearing: the 401 path below
   * retries by recursing with `options` forwarded whole, so the mode survives
   * the retry for free. A separate function would have to duplicate the header
   * construction, the network-error mapping, the refresh block and the
   * recursion — and would retry a blob request in JSON mode, a failure that
   * only ever appears after a token expiry.
   */
  parse?: 'json' | 'blob' | undefined
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
  isRetry = false,
): Promise<T> {
  // `parse` is destructured out deliberately: `...init` is spread straight
  // into fetch(), and an unrecognised key there is exactly what a future
  // runtime tightens.
  const { body, skipAuth = false, parse = 'json', headers, ...init } = options

  const requestHeaders = new Headers(headers)
  // FormData generates its own Content-Type, multipart boundary included.
  // Setting it by hand omits the boundary and the server rejects the body,
  // which is why the resume upload used to bypass this client entirely — and
  // with it the 401 refresh below, the network-error mapping, and the
  // correlation id.
  const isForm = body instanceof FormData
  if (body !== undefined && !isForm) requestHeaders.set('Content-Type', 'application/json')

  const accessToken = getAccessToken()
  if (!skipAuth && accessToken) {
    requestHeaders.set('Authorization', `Bearer ${accessToken}`)
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: requestHeaders,
      ...(body !== undefined ? { body: isForm ? body : JSON.stringify(body) } : {}),
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

    // The retry re-sends the same body. Safe for FormData, which is re-read per
    // request; it would NOT be safe for a ReadableStream body, which is
    // one-shot. Nothing sends one today.
    if (result === 'refreshed') return request<T>(path, options, true)

    if (result === 'rejected') {
      // Only a server rejection ends the session. An 'unreachable' result falls
      // through with tokens intact, and the caller sees the original 401.
      clearTokens()
      onUnauthenticated(lastRejectionReason)
      lastRejectionReason = undefined
    }
  }

  if (!response.ok) throw await parseError(response)

  // 204, and any other genuinely empty body.
  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T
  }

  // Only the success body varies. `parseError` above still reads JSON,
  // which is right: FastAPI's error envelope is JSON even when the success
  // body is bytes, so a 404 on a blob request still produces an ApiError.
  if (parse === 'blob') return (await response.blob()) as T

  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'GET' }),

  /** The raw bytes of a response, for endpoints that serve a stored file. */
  getBlob: (path: string, options?: RequestOptions) =>
    request<Blob>(path, { ...options, method: 'GET', parse: 'blob' }),

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
  lastRejectionReason = undefined
}
