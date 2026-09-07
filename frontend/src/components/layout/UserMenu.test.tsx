import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { UserMenu } from './UserMenu'

/**
 * The hook is mocked rather than wrapping this in a real AuthProvider: the
 * subject here is the menu's contents, and a real provider would drag in token
 * storage and a session restore that have nothing to do with it.
 */
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: '01a0-user', email: 'vamshi@example.com' },
    profile: { full_name: 'Banoth Vamshi' },
    logout: vi.fn(),
  }),
}))

async function openMenu() {
  const user = userEvent.setup()
  render(
    <MemoryRouter>
      <UserMenu />
    </MemoryRouter>,
  )
  await user.click(screen.getByRole('button', { name: /Banoth Vamshi/ }))
  return user
}

describe('UserMenu', () => {
  it('links to each of the account pages', async () => {
    await openMenu()

    expect(screen.getByRole('menuitem', { name: 'Your profile' })).toHaveAttribute(
      'href',
      '/profile',
    )
    expect(screen.getByRole('menuitem', { name: 'Your resume' })).toHaveAttribute('href', '/resume')
    expect(screen.getByRole('menuitem', { name: 'Saved jobs' })).toHaveAttribute(
      'href',
      '/saved-jobs',
    )
  })

  it('puts every entry in the keyboard sequence', async () => {
    /**
     * DropdownMenu finds its items with `querySelectorAll('[role="menuitem"]')`,
     * so an entry missing that role renders and is clickable but drops silently
     * out of arrow-key navigation. Nothing else in the suite would catch it.
     */
    const user = await openMenu()

    await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}')

    expect(screen.getByRole('menuitem', { name: 'Saved jobs' })).toHaveFocus()
  })

  it('keeps sign out separated from the navigation', async () => {
    // Destructive, and one row below three harmless links — it earns the rule
    // above it and its own colour.
    await openMenu()

    expect(screen.getByRole('menuitem', { name: 'Sign out' })).toHaveClass('text-red-600')
  })
})
