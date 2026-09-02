import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, __resetRefreshState, api, setUnauthenticatedHandler } from './apiClient'
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setAccessToken,
  setRefreshToken,
} from './tokenStorage'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function errorResponse(status: number, code: string, message = 'failed', details = {}): Response {
  return jsonResponse(status, {
    error: { code, message, details, correlation_id: 'corr-123' },
  })
}

describe('apiClient', () => {
  beforeEach(() => {
    clearTokens()
    __resetRefreshState()
    setUnauthenticatedHandler(() => {})
    vi.restoreAllMocks()
  })

  describe('requests', () => {
    it('attaches the access token when present', async () => {
      setAccessToken('token-abc')
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }))
      vi.stubGlobal('fetch', fetchMock)

      await api.get('/thing')

      const headers = (fetchMock.mock.calls[0]?.[1] as RequestInit).headers as Headers
      expect(headers.get('Authorization')).toBe('Bearer token-abc')
    })

    it('omits the header when skipAuth is set', async () => {
      setAccessToken('token-abc')
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
      vi.stubGlobal('fetch', fetchMock)

      await api.post('/auth/login', { email: 'a@b.com' }, { skipAuth: true })

      const headers = (fetchMock.mock.calls[0]?.[1] as RequestInit).headers as Headers
      expect(headers.get('Authorization')).toBeNull()
    })

    it('serialises the body and sets Content-Type', async () => {
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
      vi.stubGlobal('fetch', fetchMock)

      await api.post('/thing', { name: 'value' })

      const init = fetchMock.mock.calls[0]?.[1] as RequestInit
      expect(init.body).toBe('{"name":"value"}')
      expect((init.headers as Headers).get('Content-Type')).toBe('application/json')
    })

    it('returns undefined for a 204', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
      await expect(api.delete('/thing')).resolves.toBeUndefined()
    })
  })

  describe('error handling', () => {
    it('throws ApiError carrying code and correlation id', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(errorResponse(404, 'RESOURCE_NOT_FOUND', 'Nope')),
      )

      const error = await api.get('/missing').catch((e: unknown) => e)

      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).status).toBe(404)
      expect((error as ApiError).code).toBe('RESOURCE_NOT_FOUND')
      expect((error as ApiError).correlationId).toBe('corr-123')
    })

    it('exposes field errors from a 422', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(
          errorResponse(422, 'VALIDATION_ERROR', 'Invalid', {
            fields: [{ field: 'email', message: 'not a valid email', type: 'value_error' }],
          }),
        ),
      )

      const error = (await api.post('/auth/register', {}).catch((e: unknown) => e)) as ApiError

      expect(error.fieldError('email')).toBe('not a valid email')
      expect(error.fieldError('password')).toBeUndefined()
    })

    it('handles a non-JSON error body without crashing', async () => {
      // A proxy timeout returns HTML, not our envelope.
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(new Response('<html>502</html>', { status: 502 })),
      )

      const error = (await api.get('/thing').catch((e: unknown) => e)) as ApiError

      expect(error).toBeInstanceOf(ApiError)
      expect(error.status).toBe(502)
      expect(error.code).toBe('HTTP_502')
    })

    it('reports a network failure distinctly from a server error', async () => {
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

      const error = (await api.get('/thing').catch((e: unknown) => e)) as ApiError

      expect(error.code).toBe('NETWORK_ERROR')
      expect(error.status).toBe(0)
    })
  })

  describe('automatic token refresh', () => {
    it('refreshes on 401 and retries the original request', async () => {
      setAccessToken('expired')
      setRefreshToken('refresh-1')

      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce(errorResponse(401, 'INVALID_TOKEN'))
        .mockResolvedValueOnce(
          jsonResponse(200, {
            access_token: 'fresh',
            refresh_token: 'refresh-2',
            token_type: 'bearer',
            expires_in: 1800,
          }),
        )
        .mockResolvedValueOnce(jsonResponse(200, { data: 'ok' }))
      vi.stubGlobal('fetch', fetchMock)

      const result = await api.get<{ data: string }>('/protected')

      expect(result).toEqual({ data: 'ok' })
      expect(fetchMock).toHaveBeenCalledTimes(3)
      expect(getAccessToken()).toBe('fresh')
      // Rotation: the new refresh token must replace the consumed one, or the
      // next refresh would replay a dead token and trip reuse detection.
      expect(getRefreshToken()).toBe('refresh-2')
    })

    it('sends the retry with the NEW access token', async () => {
      setAccessToken('expired')
      setRefreshToken('refresh-1')

      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce(errorResponse(401, 'INVALID_TOKEN'))
        .mockResolvedValueOnce(
          jsonResponse(200, {
            access_token: 'fresh',
            refresh_token: 'refresh-2',
            token_type: 'bearer',
            expires_in: 1800,
          }),
        )
        .mockResolvedValueOnce(jsonResponse(200, {}))
      vi.stubGlobal('fetch', fetchMock)

      await api.get('/protected')

      const retryHeaders = (fetchMock.mock.calls[2]?.[1] as RequestInit).headers as Headers
      expect(retryHeaders.get('Authorization')).toBe('Bearer fresh')
    })

    it('issues exactly ONE refresh for concurrent 401s', async () => {
      // The critical case. Refresh tokens rotate and the backend treats a second
      // use of a consumed token as theft, revoking the whole family
      // (US-1.3 AC2). Three parallel requests must not produce three refreshes,
      // or two of them would be reuse and sign the user out for nothing.
      setAccessToken('expired')
      setRefreshToken('refresh-1')

      let refreshCalls = 0
      const fetchMock = vi.fn(async (url: string) => {
        if (url.endsWith('/auth/refresh')) {
          refreshCalls += 1
          return jsonResponse(200, {
            access_token: 'fresh',
            refresh_token: 'refresh-2',
            token_type: 'bearer',
            expires_in: 1800,
          })
        }
        return getAccessToken() === 'fresh'
          ? jsonResponse(200, { ok: true })
          : errorResponse(401, 'INVALID_TOKEN')
      })
      vi.stubGlobal('fetch', fetchMock)

      const results = await Promise.all([api.get('/a'), api.get('/b'), api.get('/c')])

      expect(results).toEqual([{ ok: true }, { ok: true }, { ok: true }])
      expect(refreshCalls).toBe(1)
    })

    it('does not retry more than once', async () => {
      // Guards against an infinite loop when refresh succeeds but the endpoint
      // still returns 401 — a deactivated account, for example.
      setAccessToken('expired')
      setRefreshToken('refresh-1')

      const fetchMock = vi.fn(async (url: string) =>
        url.endsWith('/auth/refresh')
          ? jsonResponse(200, {
              access_token: 'fresh',
              refresh_token: 'refresh-2',
              token_type: 'bearer',
              expires_in: 1800,
            })
          : errorResponse(401, 'AUTHENTICATION_FAILED'),
      )
      vi.stubGlobal('fetch', fetchMock)

      await expect(api.get('/protected')).rejects.toBeInstanceOf(ApiError)
      // original + refresh + one retry
      expect(fetchMock).toHaveBeenCalledTimes(3)
    })

    it('clears tokens and notifies when refresh is rejected', async () => {
      setAccessToken('expired')
      setRefreshToken('revoked')

      const onUnauthenticated = vi.fn()
      setUnauthenticatedHandler(onUnauthenticated)

      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) =>
          url.endsWith('/auth/refresh')
            ? errorResponse(401, 'TOKEN_REUSE_DETECTED')
            : errorResponse(401, 'INVALID_TOKEN'),
        ),
      )

      await expect(api.get('/protected')).rejects.toBeInstanceOf(ApiError)

      expect(getAccessToken()).toBeNull()
      expect(getRefreshToken()).toBeNull()
      expect(onUnauthenticated).toHaveBeenCalledOnce()
    })

    it('keeps tokens when refresh fails on a network error', async () => {
      // Being offline is not a reason to destroy a valid session.
      setAccessToken('expired')
      setRefreshToken('still-valid')

      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          if (url.endsWith('/auth/refresh')) throw new TypeError('Failed to fetch')
          return errorResponse(401, 'INVALID_TOKEN')
        }),
      )

      await expect(api.get('/protected')).rejects.toBeInstanceOf(ApiError)
      expect(getRefreshToken()).toBe('still-valid')
    })

    it('does not attempt refresh without a stored refresh token', async () => {
      setAccessToken('expired')

      const fetchMock = vi.fn().mockResolvedValue(errorResponse(401, 'INVALID_TOKEN'))
      vi.stubGlobal('fetch', fetchMock)

      await expect(api.get('/protected')).rejects.toBeInstanceOf(ApiError)
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })

    it('does not refresh on a 401 from a skipAuth request', async () => {
      // A failed login is a wrong password, not an expired session. Refreshing
      // here would burn the rotation chain for no reason.
      setRefreshToken('refresh-1')

      const fetchMock = vi.fn().mockResolvedValue(errorResponse(401, 'AUTHENTICATION_FAILED'))
      vi.stubGlobal('fetch', fetchMock)

      await expect(
        api.post('/auth/login', { email: 'a@b.com' }, { skipAuth: true }),
      ).rejects.toBeInstanceOf(ApiError)
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })
  })
})
