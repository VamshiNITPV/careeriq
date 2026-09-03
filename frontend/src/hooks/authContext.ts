/**
 * Auth context definition.
 *
 * Split from the provider component so that each module exports only one kind
 * of thing. React Fast Refresh cannot preserve state across edits to a module
 * that exports both a component and non-component values, which in practice
 * means every keystroke in the provider file would reset the app to logged-out.
 */

import { createContext } from 'react'
import type { LoginRequest, RegisterRequest, User } from '@/types/auth'
import type { Profile } from '@/types/profile'

/**
 * `loading` is a distinct state, not `user === null`.
 *
 * On boot, a stored refresh token means we might be signed in but do not know
 * yet. Collapsing that into "logged out" makes protected routes bounce the user
 * to /login for a frame on every hard refresh.
 */
export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

export interface AuthContextValue {
  user: User | null
  /**
   * The signed-in user's profile.
   *
   * Held here rather than in a separate provider because its lifecycle is
   * identical to the session's: loaded on boot, replaced on login, cleared on
   * logout. A second provider would have to mirror all three transitions to
   * produce exactly the same behaviour.
   */
  profile: Profile | null
  status: AuthStatus
  isAuthenticated: boolean
  login: (payload: LoginRequest) => Promise<void>
  register: (payload: RegisterRequest) => Promise<void>
  logout: () => Promise<void>
  /**
   * Apply a user returned by a mutation.
   *
   * Exists because there was previously no way to update the cached user at
   * all: VerifyEmailPage received a fresh User and discarded it, so the
   * "confirm your email" notice survived until a hard reload.
   */
  setUser: (user: User) => void
  /**
   * Apply a profile returned by a save.
   *
   * The mutation endpoints return the full resource, so the header updates in
   * the same commit as the save rather than after a follow-up fetch.
   */
  setProfile: (profile: Profile | null) => void
  refreshProfile: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)
