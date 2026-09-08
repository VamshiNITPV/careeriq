/**
 * When the user was last actually doing something.
 *
 * Kept out of React and out of `tokenStorage` on purpose: the boot path has to
 * ask "is this session stale?" *before* any effect runs, in the lazy state
 * initialiser, so this cannot be a hook. And it is a session-policy concern
 * rather than a credential one.
 *
 * **`localStorage` is the cross-tab channel, not just persistence.** Every tab
 * polls this one key, so activity in any tab keeps every tab alive, and the
 * deadline is reached by all of them within one poll of each other. That works
 * without a `storage` event listener — which is essential, because the tab that
 * *writes* never receives its own event, so an event-driven design would miss
 * exactly the case that matters.
 *
 * **`Date.now()` is wall-clock and the user can move it.** That is acceptable:
 * winding your own clock back defeats a convenience control on your own
 * machine, and the server enforces its own window on server time regardless.
 * It is also unavoidable — `performance.now()` resets per document, so it
 * cannot measure across a reload, which is the main thing this must survive.
 */

const ACTIVITY_KEY = 'careeriq.last_activity'

/**
 * The counterpart to the backend's `SESSION_IDLE_TIMEOUT_MINUTES`.
 *
 * Duplicated rather than fetched, which is why no user-facing message names a
 * number: "60 minutes" becomes a lie the day one side changes. The clean fix is
 * for the server to publish it on the token response; that is a follow-up.
 */
export const IDLE_TIMEOUT_MS = 60 * 60_000

/**
 * Both the write throttle and the poll period, so the total error is visibly at
 * most twice this — well under a percent of the window.
 */
export const ACTIVITY_RESOLUTION_MS = 30_000

/**
 * Fallback when `localStorage` throws, which Safari private mode does on access
 * rather than returning null (`tokenStorage.ts` handles the same case). Without
 * it the throw would happen inside a `setInterval` callback, where nothing
 * catches it. The feature then degrades to per-tab, which is the right failure.
 */
let inMemoryLastActivity: number | null = null
let lastWrite = 0

/** Record that the user did something. Throttled — see ACTIVITY_RESOLUTION_MS. */
export function markActivity(now: number = Date.now()): void {
  if (now - lastWrite < ACTIVITY_RESOLUTION_MS) return
  lastWrite = now
  inMemoryLastActivity = now
  try {
    localStorage.setItem(ACTIVITY_KEY, String(now))
  } catch {
    // Storage unavailable. inMemoryLastActivity above still carries this tab.
  }
}

function readLastActivity(): number | null {
  try {
    const raw = localStorage.getItem(ACTIVITY_KEY)
    if (raw !== null) {
      const parsed = Number(raw)
      // A corrupt value must fail open. Treating garbage as "infinitely stale"
      // would lock a user out of their own session with no way to recover.
      if (Number.isFinite(parsed)) return parsed
    }
  } catch {
    // Fall through to the in-memory copy.
  }
  return inMemoryLastActivity
}

/**
 * True when the last recorded activity is older than the window.
 *
 * **A missing record means fresh, not expired.** Otherwise shipping this would
 * sign out every existing session on its next page load — which would look like
 * the feature is broken rather than working.
 */
export function isSessionIdleExpired(now: number = Date.now()): boolean {
  const last = readLastActivity()
  if (last === null) return false
  return now - last >= IDLE_TIMEOUT_MS
}

export function clearActivity(): void {
  lastWrite = 0
  inMemoryLastActivity = null
  try {
    localStorage.removeItem(ACTIVITY_KEY)
  } catch {
    // Nothing to do; the in-memory copy is already cleared.
  }
}

/** Test-only: drop the module-scoped throttle, mirroring __resetRefreshState. */
export function __resetIdleState(): void {
  lastWrite = 0
  inMemoryLastActivity = null
}
