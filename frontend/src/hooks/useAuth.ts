import { useContext } from 'react'
import { AuthContext, type AuthContextValue } from './authContext'

/**
 * Access the current auth state.
 *
 * Throws when used outside the provider rather than returning undefined: a
 * missing provider is a wiring mistake that should fail immediately and
 * loudly, not surface later as an inexplicable null user.
 */
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an <AuthProvider>.')
  }
  return context
}
