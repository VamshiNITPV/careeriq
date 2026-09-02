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
  status: AuthStatus
  isAuthenticated: boolean
  login: (payload: LoginRequest) => Promise<void>
  register: (payload: RegisterRequest) => Promise<void>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)
