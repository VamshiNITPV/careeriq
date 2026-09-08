import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  AuthContext,
  type AuthContextValue,
  type AuthStatus,
  type SignedOutReason,
} from '@/hooks/authContext'
import { useIdleLogout } from '@/hooks/useIdleLogout'
import { setUnauthenticatedHandler } from '@/services/apiClient'
import { authService } from '@/services/authService'
import { profileService } from '@/services/profileService'
import { clearActivity, isSessionIdleExpired } from '@/services/idleSession'
import { clearTokens, hasStoredSession } from '@/services/tokenStorage'
import type { LoginRequest, RegisterRequest, User } from '@/types/auth'
import type { Profile } from '@/types/profile'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [profile, setProfile] = useState<Profile | null>(null)
  // Lazy initial state: with no stored refresh token there is nothing to
  // restore, so we know the answer synchronously on the first render. Starting
  // at 'loading' unconditionally would show a spinner to every first-time
  // visitor before landing them on the login page — a flash of nothing for the
  // one group guaranteed not to have a session.
  const [status, setStatus] = useState<AuthStatus>(() => {
    if (!hasStoredSession()) return 'unauthenticated'
    // Idle since before the window closed. Cleared here rather than in an
    // effect so the restore below sees no stored session and makes no request
    // for one that is already over. Idempotent, which matters because
    // StrictMode invokes this initialiser twice.
    if (isSessionIdleExpired()) {
      clearTokens()
      clearActivity()
      return 'unauthenticated'
    }
    return 'loading'
  })
  /** Why the user is looking at the login page. Cleared on the next sign-in. */
  const [signedOutReason, setSignedOutReason] = useState<SignedOutReason>(() =>
    hasStoredSession() || !isSessionIdleExpired() ? null : 'idle',
  )

  const loadProfile = useCallback(async () => {
    // Never allowed to fail the caller. In restore() a rejection here would
    // land in the catch below and sign the user out over a profile fetch.
    try {
      setProfile(await profileService.get())
    } catch {
      setProfile(null)
    }
  }, [])

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
        // The profile is fetched with its own error handling inside
        // loadProfile, so it can never reject this Promise.all and take the
        // session down with it.
        const [currentUser] = await Promise.all([authService.me(), loadProfile()])
        if (cancelled) return
        setUser(currentUser)
        setStatus('authenticated')
      } catch {
        if (cancelled) return
        clearTokens()
        setUser(null)
        setProfile(null)
        setStatus('unauthenticated')
      }
    }

    void restore()
    return () => {
      // The user may navigate away mid-request; without this, resolving after
      // unmount sets state on a dead component.
      cancelled = true
    }
  }, [loadProfile])

  /**
   * React to a session the client could not recover — a revoked or reused
   * refresh token. The API client cannot import React, so it calls back here.
   */
  useEffect(() => {
    setUnauthenticatedHandler((reason) => {
      setUser(null)
      setProfile(null)
      setStatus('unauthenticated')
      // The server refused the refresh because the session had gone idle.
      // Without this the whole server-side half of the feature is invisible and
      // the sign-out looks arbitrary.
      if (reason === 'idle') setSignedOutReason('idle')
    })
    return () => setUnauthenticatedHandler(() => {})
  }, [])

  const login = useCallback(
    async (payload: LoginRequest) => {
      const response = await authService.login(payload)
      setUser(response.user)
      setStatus('authenticated')
      setSignedOutReason(null)
      // Not awaited: the redirect should not wait on the profile. The header
      // falls back to email-derived initials for one paint.
      void loadProfile()
    },
    [loadProfile],
  )

  const register = useCallback(
    async (payload: RegisterRequest) => {
      const response = await authService.register(payload)
      setUser(response.user)
      setStatus('authenticated')
      setSignedOutReason(null)
      void loadProfile()
    },
    [loadProfile],
  )

  const logout = useCallback(async (reason: SignedOutReason = null) => {
    try {
      await authService.logout()
    } finally {
      // In a finally, because authService.logout() rejects on a 500 or while
      // offline. Clearing only on success left the app believing it was signed
      // in with no tokens, and every request 401ing with no way out.
      clearActivity()
      setUser(null)
      setProfile(null)
      setStatus('unauthenticated')
      setSignedOutReason(reason)
    }
  }, [])

  // The live-tab half of the idle timeout. Failures are swallowed: an offline
  // sign-out must still clear local state, which the finally above guarantees,
  // and an unhandled rejection inside an interval callback has nowhere to go.
  const onIdle = useCallback(() => {
    void logout('idle').catch(() => {})
  }, [logout])
  useIdleLogout(status === 'authenticated', onIdle)

  // Memoised so consumers do not re-render on every provider render purely
  // because the context object identity changed.
  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      profile,
      status,
      isAuthenticated: status === 'authenticated',
      login,
      register,
      logout,
      signedOutReason,
      setUser,
      setProfile,
      refreshProfile: loadProfile,
    }),
    [user, profile, status, signedOutReason, login, register, logout, loadProfile],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
