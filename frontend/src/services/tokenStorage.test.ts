import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  hasStoredSession,
  setAccessToken,
  setRefreshToken,
} from './tokenStorage'

describe('tokenStorage', () => {
  beforeEach(() => {
    clearTokens()
    localStorage.clear()
  })

  describe('access token', () => {
    it('round-trips in memory', () => {
      setAccessToken('abc123')
      expect(getAccessToken()).toBe('abc123')
    })

    it('is never written to localStorage', () => {
      // The whole point of holding it in memory: persisted storage is readable
      // by any injected script for as long as the value sits there.
      setAccessToken('super-secret-access-token')

      const stored = Object.keys(localStorage).map((k) => localStorage.getItem(k))
      expect(stored).not.toContain('super-secret-access-token')
      expect(localStorage.length).toBe(0)
    })

    it('can be cleared', () => {
      setAccessToken('abc123')
      setAccessToken(null)
      expect(getAccessToken()).toBeNull()
    })
  })

  describe('refresh token', () => {
    it('persists so a reload does not sign the user out', () => {
      setRefreshToken('refresh-abc')
      expect(getRefreshToken()).toBe('refresh-abc')
    })

    it('is removed rather than stored as the string "null"', () => {
      setRefreshToken('refresh-abc')
      setRefreshToken(null)

      expect(getRefreshToken()).toBeNull()
      expect(localStorage.length).toBe(0)
    })
  })

  describe('when storage is unavailable', () => {
    it('reads as no session instead of throwing', () => {
      // Safari private mode and hardened browser settings throw on access. A
      // crash here would render a blank page on boot.
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('SecurityError')
      })

      expect(() => getRefreshToken()).not.toThrow()
      expect(getRefreshToken()).toBeNull()
    })

    it('swallows write failures', () => {
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('QuotaExceededError')
      })

      expect(() => setRefreshToken('refresh-abc')).not.toThrow()
    })
  })

  describe('clearTokens', () => {
    it('clears both tokens', () => {
      setAccessToken('access')
      setRefreshToken('refresh')

      clearTokens()

      expect(getAccessToken()).toBeNull()
      expect(getRefreshToken()).toBeNull()
      expect(hasStoredSession()).toBe(false)
    })
  })

  describe('hasStoredSession', () => {
    it('tracks the refresh token, not the access token', () => {
      // After a reload only the refresh token survives, so it alone determines
      // whether restoring a session is worth attempting.
      setAccessToken('access-only')
      expect(hasStoredSession()).toBe(false)

      setRefreshToken('refresh')
      expect(hasStoredSession()).toBe(true)
    })
  })
})
