/**
 * Token storage.
 *
 * The two tokens are stored differently on purpose.
 *
 * **Access token — in memory only.** It never touches localStorage, so a
 * successful XSS cannot read it back later, and it is gone when the tab closes.
 * Losing it on reload costs one refresh call, which is cheap.
 *
 * **Refresh token — localStorage.** It has to survive a page reload, or every
 * refresh would log the user out. That means an XSS *can* steal it, which is a
 * real and unavoidable cost of this approach.
 *
 * The honest comparison: an httpOnly, SameSite=Strict cookie would put the
 * refresh token out of JavaScript's reach entirely and is the stronger option.
 * It is not used here because the SPA and API are served from different origins
 * in production, so the cookie would need SameSite=None, which reintroduces
 * CSRF and requires a token defence of its own. That tradeoff is worth
 * revisiting in Phase 11 if both are served behind one hostname.
 *
 * What limits the damage meanwhile is server-side: refresh tokens rotate on
 * every use and reuse is detected, so a stolen token is usable at most once
 * before the whole family is revoked and the real user is logged out — a loud,
 * visible failure rather than silent long-term access (ADR-014, US-1.3 AC2).
 */

const REFRESH_TOKEN_KEY = 'careeriq.refresh_token'

/** Deliberately module-scoped rather than persisted. See the note above. */
let accessToken: string | null = null

export function getAccessToken(): string | null {
  return accessToken
}

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function getRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_TOKEN_KEY)
  } catch {
    // Safari private mode and hardened browser settings throw on access rather
    // than returning null. Treat it as "no stored session" — the user simply
    // has to sign in again, which is far better than a blank crashing page.
    return null
  }
}

export function setRefreshToken(token: string | null): void {
  try {
    if (token === null) {
      localStorage.removeItem(REFRESH_TOKEN_KEY)
    } else {
      localStorage.setItem(REFRESH_TOKEN_KEY, token)
    }
  } catch {
    // Storage unavailable or quota exceeded. The session still works for this
    // tab via the in-memory access token; it just will not survive a reload.
  }
}

export function clearTokens(): void {
  setAccessToken(null)
  setRefreshToken(null)
}

export function hasStoredSession(): boolean {
  return getRefreshToken() !== null
}
