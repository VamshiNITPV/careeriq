import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { DropdownMenu, menuItemClass } from './DropdownMenu'

/**
 * The behavioural details a hand-rolled menu usually gets wrong. Each test here
 * corresponds to a way keyboard or pointer users get stranded.
 */

function renderMenu() {
  return render(
    <MemoryRouter>
      <DropdownMenu label="Account menu" trigger={<span>avatar</span>}>
        <button role="menuitem" tabIndex={-1} type="button" className={menuItemClass}>
          First
        </button>
        <button role="menuitem" tabIndex={-1} type="button" className={menuItemClass}>
          Second
        </button>
        <button role="menuitem" tabIndex={-1} type="button" className={menuItemClass}>
          Third
        </button>
      </DropdownMenu>
      <button type="button">outside</button>
    </MemoryRouter>,
  )
}

const trigger = () => screen.getByRole('button', { name: 'Account menu' })

describe('DropdownMenu', () => {
  it('starts closed and announces its state', () => {
    renderMenu()

    expect(trigger()).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('opens on click', async () => {
    const user = userEvent.setup()
    renderMenu()

    await user.click(trigger())

    expect(trigger()).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('menu')).toBeInTheDocument()
  })

  it('closes on a second click of the trigger', async () => {
    // The document pointerdown handler must exclude the trigger, or it closes
    // the menu in the same gesture that opens it and nothing appears to work.
    const user = userEvent.setup()
    renderMenu()

    await user.click(trigger())
    await user.click(trigger())

    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  describe('keyboard', () => {
    it('ArrowDown on the trigger opens and focuses the first item', async () => {
      const user = userEvent.setup()
      renderMenu()

      trigger().focus()
      await user.keyboard('{ArrowDown}')

      expect(screen.getByRole('menuitem', { name: 'First' })).toHaveFocus()
    })

    it('ArrowUp on the trigger opens and focuses the last item', async () => {
      const user = userEvent.setup()
      renderMenu()

      trigger().focus()
      await user.keyboard('{ArrowUp}')

      expect(screen.getByRole('menuitem', { name: 'Third' })).toHaveFocus()
    })

    it('wraps around at the end', async () => {
      const user = userEvent.setup()
      renderMenu()

      trigger().focus()
      await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}')

      expect(screen.getByRole('menuitem', { name: 'First' })).toHaveFocus()
    })

    it('Escape closes and returns focus to the trigger', async () => {
      // Without the focus return the user is dropped at the top of the
      // document and has to tab all the way back.
      const user = userEvent.setup()
      renderMenu()

      trigger().focus()
      await user.keyboard('{ArrowDown}')
      await user.keyboard('{Escape}')

      expect(screen.queryByRole('menu')).not.toBeInTheDocument()
      expect(trigger()).toHaveFocus()
    })

    it('Tab closes the menu without trapping focus', async () => {
      // A menu button is not a modal dialog. Trapping Tab is the most common
      // hand-rolled menu bug and leaves keyboard users unable to move past it.
      //
      // The assertion is that the menu closes and focus is no longer held
      // inside it. Where focus lands next is deliberately not asserted: that
      // is the browser's sequential navigation, and jsdom does not reproduce
      // it faithfully enough to pin.
      const user = userEvent.setup()
      renderMenu()

      trigger().focus()
      await user.keyboard('{ArrowDown}')
      expect(screen.getByRole('menuitem', { name: 'First' })).toHaveFocus()

      await user.tab()

      expect(screen.queryByRole('menu')).not.toBeInTheDocument()
      expect(document.activeElement?.getAttribute('role')).not.toBe('menuitem')
    })
  })

  it('closes when pointing outside', async () => {
    const user = userEvent.setup()
    renderMenu()

    await user.click(trigger())
    await user.click(screen.getByRole('button', { name: 'outside' }))

    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes after an item is chosen', async () => {
    const user = userEvent.setup()
    renderMenu()

    await user.click(trigger())
    await user.click(screen.getByRole('menuitem', { name: 'Second' }))

    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })
})
