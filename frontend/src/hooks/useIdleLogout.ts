import { useEffect } from 'react'
import {
  ACTIVITY_RESOLUTION_MS,
  isSessionIdleExpired,
  markActivity,
} from '@/services/idleSession'
import { hasStoredSession } from '@/services/tokenStorage'

/**
 * Sign the user out after a spell of doing nothing (US-1.3 AC4).
 *
 * Called from AuthProvider rather than mounted as a component, so all session
 * policy lives in one file beside the unauthenticated handler — and so it can
 * read the status it needs from the context it would otherwise have to consume.
 *
 * **This is not the enforcement.** The server refuses a refresh for an idle
 * session and revokes the family, which is what covers a closed browser or a
 * stolen refresh token. This layer covers the live tab, and it is what stops a
 * live tab generating the background traffic that would keep the server's
 * window from ever binding.
 */

/** Real human input. Anything here *writes* the timestamp. */
const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'touchstart', 'scroll'] as const

/**
 * Coming back to the tab *checks* the deadline; it never marks activity.
 *
 * Treating `visibilitychange` as activity is the tempting mistake: returning to
 * a tab after two hours would refresh the timestamp and cancel precisely the
 * sign-out this exists for.
 */
const CHECK_EVENTS = ['visibilitychange', 'focus'] as const

export function useIdleLogout(isAuthenticated: boolean, onIdle: () => void): void {
  useEffect(() => {
    // Nothing to time while signed out or while the boot restore is still in
    // flight — otherwise this fires against the login page in a loop.
    if (!isAuthenticated) return

    // Arriving authenticated counts as being here.
    markActivity()

    const check = () => {
      // Also covers a manual sign-out in another tab: the refresh token is
      // gone from shared storage, so this tab follows within one poll. That
      // closes a pre-existing gap for one line.
      if (isSessionIdleExpired() || !hasStoredSession()) onIdle()
    }

    const onActivity = () => markActivity()

    for (const name of ACTIVITY_EVENTS) {
      // capture: scroll does not bubble, so a listener without it misses every
      // inner scroll container. passive: none of these are ever cancelled.
      //
      // mousemove is deliberately absent — a nudged desk or a jittery trackpad
      // would keep a session alive indefinitely.
      document.addEventListener(name, onActivity, { capture: true, passive: true })
    }
    for (const name of CHECK_EVENTS) {
      window.addEventListener(name, check)
    }

    /*
      A poll comparing timestamps, not a `setTimeout` re-armed on every event.

      The decisive reason is suspend: timers do not advance while a laptop is
      asleep and their behaviour on resume is platform-dependent, whereas a
      timestamp comparison is correct by construction — the first tick after
      waking computes true elapsed wall-clock time and signs out immediately.
      Background tabs also throttle timers heavily, which makes a long
      `setTimeout` fire late for the same reason.
    */
    const timer = window.setInterval(check, ACTIVITY_RESOLUTION_MS)

    return () => {
      window.clearInterval(timer)
      for (const name of ACTIVITY_EVENTS) {
        document.removeEventListener(name, onActivity, { capture: true })
      }
      for (const name of CHECK_EVENTS) {
        window.removeEventListener(name, check)
      }
    }
  }, [isAuthenticated, onIdle])
}
