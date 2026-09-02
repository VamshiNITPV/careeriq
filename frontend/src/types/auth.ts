/** Auth types mirroring backend/app/schemas/auth.py. */

export type UserRole = 'USER' | 'ADMIN'
export type AuthProvider = 'LOCAL' | 'GOOGLE'

export interface User {
  id: string
  email: string
  role: UserRole
  auth_provider: AuthProvider
  is_active: boolean
  email_verified_at: string | null
  last_login_at: string | null
  created_at: string
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  /** Access token lifetime in seconds. */
  expires_in: number
}

export interface AuthResponse {
  user: User
  tokens: TokenPair
}

export interface RegisterRequest {
  email: string
  password: string
  full_name?: string
}

export interface LoginRequest {
  email: string
  password: string
}

/** Mirrors MIN_PASSWORD_LENGTH in backend/app/schemas/auth.py (US-1.1 AC1). */
export const MIN_PASSWORD_LENGTH = 10
export const MAX_PASSWORD_LENGTH = 128
