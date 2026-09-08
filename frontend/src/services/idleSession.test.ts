import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ACTIVITY_RESOLUTION_MS,
  IDLE_TIMEOUT_MS,
  __resetIdleState,
  clearActivity,
  isSessionIdleExpired,
  markActivity,
} from './idleSession'

// setup.ts clears localStorage after each test, but the module-scoped throttle
// does not clear itself — same reason apiClient exposes __resetRefreshState.
beforeEach(() => __resetIdleState())
afterEach(() => vi.restoreAllMocks())

describe('idleSession', () => {
  it('is not expired immediately after activity', () => {
    const now = 1_000_000

    markActivity(now)

    expect(isSessionIdleExpired(now + IDLE_TIMEOUT_MS - 1)).toBe(false)
  })

  it('is expired once the window has passed', () => {
    const now = 1_000_000

    markActivity(now)

    expect(isSessionIdleExpired(now + IDLE_TIMEOUT_MS)).toBe(true)
  })

  it('treats no record at all as fresh', () => {
    // The load-bearing one. If an absent key read as "infinitely stale", then
    // shipping this would sign out every existing session on its next page
    // load — which looks like the feature is broken rather than working.
    expect(isSessionIdleExpired()).toBe(false)
  })

  it('treats a corrupt record as fresh', () => {
    // A value must never be able to lock someone out of their own session.
    localStorage.setItem('careeriq.last_activity', 'not a number')

    expect(isSessionIdleExpired()).toBe(false)
  })

  it('throttles writes, so an event storm is not a storage storm', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const now = 1_000_000

    markActivity(now)
    markActivity(now + 1)
    markActivity(now + ACTIVITY_RESOLUTION_MS - 1)

    expect(setItem).toHaveBeenCalledTimes(1)

    markActivity(now + ACTIVITY_RESOLUTION_MS)

    expect(setItem).toHaveBeenCalledTimes(2)
  })

  it('survives storage that throws, rather than failing inside a timer', () => {
    // Safari private mode throws on access. This runs inside a setInterval
    // callback, where an exception is caught by nothing at all.
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('nope')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('nope')
    })
    const now = 1_000_000

    expect(() => markActivity(now)).not.toThrow()
    // Degraded to this tab only, which is the right failure — the in-memory
    // copy still answers.
    expect(isSessionIdleExpired(now + IDLE_TIMEOUT_MS)).toBe(true)
  })

  it('forgets the session when cleared', () => {
    const now = 1_000_000
    markActivity(now)

    clearActivity()

    expect(isSessionIdleExpired(now + IDLE_TIMEOUT_MS)).toBe(false)
  })
})
