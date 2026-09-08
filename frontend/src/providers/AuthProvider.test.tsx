import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuth } from '@/hooks/useAuth'
import { authService } from '@/services/authService'
import {
  ACTIVITY_RESOLUTION_MS,
  IDLE_TIMEOUT_MS,
  __resetIdleState,
  markActivity,
} from '@/services/idleSession'
import { profileService } from '@/services/profileService'
import { setRefreshToken } from '@/services/tokenStorage'
import { AuthProvider } from './AuthProvider'

/**
 * The idle session timeout (US-1.3 AC4), browser half.
 *
 * `fireEvent`, never `userEvent`, because fake timers are on throughout —
 * ResumePage.test.tsx already records why: user-event's internal waits do not
 * resolve under fake timers even with `advanceTimers` wired up, and the test
 * hangs with no useful message.
 *
 * A genuine cross-tab test needs two browsing contexts and therefore Playwright.
 * What is asserted here is that one tab reaches the deadline from a shared
 * timestamp, which is the mechanism the cross-tab behaviour is built on.
 */

const USER = { id: 'u1', email: 'priya@example.com', full_name: 'Priya S.' }

function Probe() {
  const { status } = useAuth()
  return <span aria-label="status">{status}</span>
}

function renderProvider() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </MemoryRouter>,
  )
}

/** Let the boot restore's promises settle without advancing the idle clock. */
async function settle() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
}

describe('AuthProvider idle timeout', () => {
  let logout: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    // Fake Date too: the watcher compares timestamps, so without a faked clock
    // the interval would tick forever and never see any elapsed time.
    vi.useFakeTimers()
    __resetIdleState()
    localStorage.clear()
    vi.spyOn(authService, 'me').mockResolvedValue(USER as never)
    vi.spyOn(profileService, 'get').mockResolvedValue(null as never)
    logout = vi.spyOn(authService, 'logout').mockResolvedValue(undefined as never)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('signs the user out once the window passes', async () => {
    setRefreshToken('stored-refresh')
    renderProvider()
    await settle()
    expect(screen.getByLabelText('status')).toHaveTextContent('authenticated')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(IDLE_TIMEOUT_MS + ACTIVITY_RESOLUTION_MS)
    })

    expect(logout).toHaveBeenCalled()
    expect(screen.getByLabelText('status')).toHaveTextContent('unauthenticated')
  })

  it('keeps the session while the user is doing something', async () => {
    setRefreshToken('stored-refresh')
    renderProvider()
    await settle()

    // Half the window, a keystroke, then half again. Neither half alone
    // reaches the deadline, and the keystroke must reset the clock.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(IDLE_TIMEOUT_MS * 0.6)
    })
    fireEvent.keyDown(document, { key: 'a' })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(IDLE_TIMEOUT_MS * 0.6)
    })

    expect(logout).not.toHaveBeenCalled()
    expect(screen.getByLabelText('status')).toHaveTextContent('authenticated')
  })

  it('does not treat coming back to the tab as activity', async () => {
    /*
     * The regression test for the tempting mistake. If `visibilitychange` were
     * an activity event, returning to a tab after two hours would refresh the
     * timestamp and cancel exactly the sign-out this feature exists for.
     */
    setRefreshToken('stored-refresh')
    renderProvider()
    await settle()

    // A backgrounded tab, where timers are throttled or suspended: the clock
    // moved but the poll never ran. Written directly rather than by advancing
    // timers, because advancing them would fire the poll and sign the user out
    // before the event under test could matter.
    __resetIdleState()
    markActivity(Date.now() - IDLE_TIMEOUT_MS - 1)

    await act(async () => {
      fireEvent(document, new Event('visibilitychange'))
      fireEvent(window, new Event('visibilitychange'))
      // Deliberately not enough for the 30s poll to fire on its own, so the
      // only thing that can act here is the event.
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(logout).toHaveBeenCalled()
  })

  it('does not restore a session that was already stale on arrival', async () => {
    // The strongest statement of "do not revive a dead session": no /auth/me
    // round trip is made at all, because the lazy initialiser clears the tokens
    // before the restore effect can run.
    const me = vi.spyOn(authService, 'me')
    setRefreshToken('stored-refresh')
    markActivity(Date.now() - IDLE_TIMEOUT_MS - 1)

    renderProvider()
    await settle()

    expect(me).not.toHaveBeenCalled()
    expect(screen.getByLabelText('status')).toHaveTextContent('unauthenticated')
  })

  it('does nothing at all when nobody is signed in', async () => {
    renderProvider()
    await settle()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(IDLE_TIMEOUT_MS * 3)
    })

    // Without the status guard this would fire logout() against the login
    // page on every tick.
    expect(logout).not.toHaveBeenCalled()
  })

  it('clears local state even when the sign-out request fails', async () => {
    // Previously the state was cleared only after `await authService.logout()`
    // resolved, so a 500 or an offline blip left the app believing it was
    // signed in with no tokens, and every request 401ing with no way out.
    logout.mockRejectedValue(new Error('offline') as never)
    setRefreshToken('stored-refresh')
    renderProvider()
    await settle()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(IDLE_TIMEOUT_MS + ACTIVITY_RESOLUTION_MS)
    })

    expect(screen.getByLabelText('status')).toHaveTextContent('unauthenticated')
  })
})
