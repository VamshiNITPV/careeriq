import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
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
    // No "Saved jobs" entry: that page was a second view of the rows now on
    // /applications, and two views of one list can disagree.
    expect(screen.queryByRole('menuitem', { name: 'Saved jobs' })).not.toBeInTheDocument()
  })

  it('puts every entry in the keyboard sequence', async () => {
    /**
     * DropdownMenu finds its items with `querySelectorAll('[role="menuitem"]')`,
     * so an entry missing that role renders and is clickable but drops silently
     * out of arrow-key navigation. Nothing else in the suite would catch it.
     */
    const user = await openMenu()

    // Three presses reaches the last entry now that Saved jobs is gone. Landing
    // on Sign out is the stronger assertion anyway: it is the item furthest
    // from the trigger, so reaching it proves every one before it participates.
    await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}')

    expect(screen.getByRole('menuitem', { name: 'Sign out' })).toHaveFocus()
  })

  it('keeps sign out separated from the navigation', async () => {
    // Destructive, and one row below three harmless links — it earns the rule
    // above it and its own colour.
    await openMenu()

    expect(screen.getByRole('menuitem', { name: 'Sign out' })).toHaveClass('text-red-600')
  })
})

/**
 * Opening on hover (fine pointers only).
 *
 * `matchMedia` is stubbed per test rather than globally, so each one states the
 * device it is assuming. The suite-wide default from `test/setup.ts` is
 * `matches: false` — a device that cannot hover — which is why these have to opt
 * in and the touch test below does not.
 */
describe('UserMenu on a device with a pointer', () => {
  function withFinePointer(matches: boolean) {
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) =>
        ({
          matches,
          media: query,
          onchange: null,
          addEventListener: () => {},
          removeEventListener: () => {},
          dispatchEvent: () => false,
          addListener: () => {},
          removeListener: () => {},
        }) as MediaQueryList,
    )
  }

  function renderMenu() {
    render(
      <MemoryRouter>
        <UserMenu />
      </MemoryRouter>,
    )
    return screen.getByRole('button', { name: /Banoth Vamshi/ })
  }

  afterEach(() => {
    vi.useRealTimers()
  })

  it('opens when the pointer rests on it', async () => {
    withFinePointer(true)
    vi.useFakeTimers()
    const trigger = renderMenu()

    fireEvent.pointerEnter(trigger.parentElement as HTMLElement)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()

    await act(async () => {
      vi.advanceTimersByTime(150)
    })

    expect(screen.getByRole('menu')).toBeInTheDocument()
  })

  it('ignores a cursor passing over on its way somewhere else', async () => {
    withFinePointer(true)
    vi.useFakeTimers()
    const trigger = renderMenu()
    const root = trigger.parentElement as HTMLElement

    // In and out again inside the open delay. Without an intent delay this is
    // the gesture that flings menus open behind someone crossing the header.
    fireEvent.pointerEnter(root)
    await act(async () => {
      vi.advanceTimersByTime(60)
    })
    fireEvent.pointerLeave(root)
    await act(async () => {
      vi.advanceTimersByTime(500)
    })

    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes again once the pointer leaves', async () => {
    withFinePointer(true)
    vi.useFakeTimers()
    const trigger = renderMenu()
    const root = trigger.parentElement as HTMLElement

    fireEvent.pointerEnter(root)
    await act(async () => {
      vi.advanceTimersByTime(150)
    })
    expect(screen.getByRole('menu')).toBeInTheDocument()

    fireEvent.pointerLeave(root)
    // Not gone yet: the close delay is what lets a cursor cross the 8px gap
    // between the trigger and the panel without the menu shutting mid-reach.
    await act(async () => {
      vi.advanceTimersByTime(100)
    })
    expect(screen.getByRole('menu')).toBeInTheDocument()

    await act(async () => {
      vi.advanceTimersByTime(200)
    })
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('does nothing on hover where there is no pointer, and still opens on tap', async () => {
    withFinePointer(false)
    const user = userEvent.setup()
    const trigger = renderMenu()

    fireEvent.pointerEnter(trigger.parentElement as HTMLElement)
    // A tap fires pointerenter and then click. If hover were not gated, the
    // enter would open the menu and the click would toggle it straight back
    // shut — two taps to open, looking broken, for the people least able to
    // work around it.
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()

    await user.click(trigger)
    expect(screen.getByRole('menu')).toBeInTheDocument()
  })
})
