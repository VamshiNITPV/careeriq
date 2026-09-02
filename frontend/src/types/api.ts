/**
 * Types mirroring the backend contract (docs/api.md).
 *
 * Hand-written for now. Once the API stabilises these should be generated from
 * `/openapi.json` so drift becomes impossible — a hand-maintained copy of a
 * contract is a copy that will eventually be wrong. Tracked as Phase 12 work.
 */

/** The single error envelope every non-2xx response uses (api.md 1.4). */
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details?: Record<string, unknown>
    correlation_id?: string
  }
}

/** A field-level validation failure, as returned inside `details.fields`. */
export interface FieldError {
  field: string
  message: string
  type: string
}

/**
 * Error codes the UI branches on.
 *
 * `message` is explicitly *not* stable — the backend may reword it freely — so
 * any behaviour keyed off a message string is a latent bug. Branch on `code`.
 */
export const ErrorCode = {
  ValidationError: 'VALIDATION_ERROR',
  AuthenticationFailed: 'AUTHENTICATION_FAILED',
  InvalidToken: 'INVALID_TOKEN',
  TokenReuseDetected: 'TOKEN_REUSE_DETECTED',
  PermissionDenied: 'PERMISSION_DENIED',
  ResourceNotFound: 'RESOURCE_NOT_FOUND',
  RegistrationFailed: 'REGISTRATION_FAILED',
  RateLimitExceeded: 'RATE_LIMIT_EXCEEDED',
  InternalError: 'INTERNAL_ERROR',
  /** Client-side only: the request never reached the server. */
  NetworkError: 'NETWORK_ERROR',
} as const

export type ErrorCodeValue = (typeof ErrorCode)[keyof typeof ErrorCode]

export interface MessageResponse {
  message: string
}

export interface HealthResponse {
  status: string
  version: string
  environment: string
}
