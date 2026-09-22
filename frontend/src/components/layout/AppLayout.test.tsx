import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AppLayout } from './AppLayout'

/**
 * The account menu is the subject of its own file; here it only has to mount,
 * so `useAuth` is stubbed rather than wrapping this in a real provider that
 * would drag in token storage and a session restore.
 */
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: '01a0-user', email: 'vamshi@example.com' },
    profile: { full_name: 'Banoth Vamshi' },
    logout: vi.fn(),
  }),
}))

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <AppLayout />
    </MemoryRouter>,
  )
}

describe('AppLayout navigation', () => {
  it('carries four links, and Resume is not one of them', () => {
    renderLayout()

    // Both navs render the same list, so scope to one. Queried by name rather
    // than by counting, so a future addition does not fail this for the wrong
    // reason.
    const nav = screen.getAllByRole('navigation', { name: 'Main' })[0] as HTMLElement

    expect(within(nav).getByRole('link', { name: 'Dashboard' })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Jobs' })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Applications' })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Skills' })).toBeInTheDocument()

    // It lives in the account menu as "Your resume". Two entries to the same
    // page cost width on the one surface that has none to spare.
    expect(within(nav).queryByRole('link', { name: 'Resume' })).not.toBeInTheDocument()
  })

  it('still opens and closes the disclosure on click', async () => {
    const user = userEvent.setup()
    renderLayout()

    const trigger = screen.getByRole('button', { name: 'Open menu' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    // One nav while closed: the panel carries `hidden`, which takes it out of
    // the accessibility tree along with its links.
    expect(screen.getAllByRole('navigation', { name: 'Main' })).toHaveLength(1)

    await user.click(trigger)

    // Two once open. aria-expanded alone would have gone on saying "open"
    // while the panel showed nothing — the restructure into an anchored
    // dropdown is exactly the kind of change that can break one without the
    // other.
    expect(screen.getAllByRole('navigation', { name: 'Main' })).toHaveLength(2)

    // The accessible name flips with the state, so this also proves the label
    // is not stale — a button still reading "Open menu" while the panel is open
    // tells a screen-reader user the opposite of what is true.
    expect(screen.getByRole('button', { name: 'Close menu' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )

    await user.click(screen.getByRole('button', { name: 'Close menu' }))
    expect(screen.getByRole('button', { name: 'Open menu' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
  })
})
