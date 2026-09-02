/** Auth API calls (api.md 2.1). Token side effects live here, not in components. */

import type {
  AuthResponse,
  LoginRequest,
  RegisterRequest,
  User,
} from '@/types/auth'
import type { MessageResponse } from '@/types/api'
import { api } from './apiClient'
import { clearTokens, getRefreshToken, setAccessToken, setRefreshToken } from './tokenStorage'

function storeTokens(response: AuthResponse): AuthResponse {
  setAccessToken(response.tokens.access_token)
  setRefreshToken(response.tokens.refresh_token)
  return response
}

export const authService = {
  async register(payload: RegisterRequest): Promise<AuthResponse> {
    // skipAuth: a stale Authorization header from a previous session would be
    // sent otherwise, and the endpoint has no business seeing it.
    const response = await api.post<AuthResponse>('/auth/register', payload, {
      skipAuth: true,
    })
    return storeTokens(response)
  },

  async login(payload: LoginRequest): Promise<AuthResponse> {
    const response = await api.post<AuthResponse>('/auth/login', payload, {
      skipAuth: true,
    })
    return storeTokens(response)
  },

  async logout(): Promise<void> {
    const refreshToken = getRefreshToken()
    try {
      if (refreshToken) {
        await api.post<MessageResponse>(
          '/auth/logout',
          { refresh_token: refreshToken },
          { skipAuth: true },
        )
      }
    } finally {
      // Always clear locally, even if the server call failed. A user who clicks
      // "sign out" must end up signed out of this browser regardless of whether
      // the network cooperated; the server token expires on its own.
      clearTokens()
    }
  },

  /** Current user. Also serves as the session probe on app boot. */
  me(): Promise<User> {
    return api.get<User>('/auth/me')
  },

  changePassword(currentPassword: string, newPassword: string): Promise<MessageResponse> {
    return api.post<MessageResponse>('/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    })
  },
}
