import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { AuthContext, type AuthContextValue, type AuthStatus } from '@/hooks/authContext'
import { setUnauthenticatedHandler } from '@/services/apiClient'
import { authService } from '@/services/authService'
import { clearTokens, hasStoredSession } from '@/services/tokenStorage'
import type { LoginRequest, RegisterRequest, User } from '@/types/auth'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  // Lazy initial state: with no stored refresh token there is nothing to
  // restore, so we know the answer synchronously on the first render. Starting
  // at 'loading' unconditionally would show a spinner to every first-time
  // visitor before landing them on the login page — a flash of nothing for the
  // one group guaranteed not to have a session.
  const [status, setStatus] = useState<AuthStatus>(() =>
    hasStoredSession() ? 'loading' : 'unauthenticated',
  )

  /**
   * Restore the session on boot.
   *
   * The access token lives in memory only, so after a page reload we hold just
   * a refresh token. Calling /auth/me triggers the client's automatic refresh,
   * which both mints a new access token and confirms the session is still
   * valid server-side — a token that looks fine locally may have been revoked.
   */
  useEffect(() => {
    let cancelled = false

    // Already resolved synchronously above; no request to make.
    if (!hasStoredSession()) return

    async function restore() {
      try {
        const currentUser = await authService.me()
        if (cancelled) return
        setUser(currentUser)
        setStatus('authenticated')
      } catch {
        if (cancelled) return
        clearTokens()
        setUser(null)
        setStatus('unauthenticated')
      }
    }

    void restore()
    return () => {
      // The user may navigate away mid-request; without this, resolving after
      // unmount sets state on a dead component.
      cancelled = true
    }
  }, [])

  /**
   * React to a session the client could not recover — a revoked or reused
   * refresh token. The API client cannot import React, so it calls back here.
   */
  useEffect(() => {
    setUnauthenticatedHandler(() => {
      setUser(null)
      setStatus('unauthenticated')
    })
    return () => setUnauthenticatedHandler(() => {})
  }, [])

  const login = useCallback(async (payload: LoginRequest) => {
    const response = await authService.login(payload)
    setUser(response.user)
    setStatus('authenticated')
  }, [])

  const register = useCallback(async (payload: RegisterRequest) => {
    const response = await authService.register(payload)
    setUser(response.user)
    setStatus('authenticated')
  }, [])

  const logout = useCallback(async () => {
    await authService.logout()
    setUser(null)
    setStatus('unauthenticated')
  }, [])

  // Memoised so consumers do not re-render on every provider render purely
  // because the context object identity changed.
  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      status,
      isAuthenticated: status === 'authenticated',
      login,
      register,
      logout,
    }),
    [user, status, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
