import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { Combobox } from './Combobox'
import type { ComboboxOption } from './comboboxCore'

/**
 * A small fixed list rather than the real country data, so these tests do not
 * start failing when someone edits src/data/countries.ts.
 */
const OPTIONS: readonly ComboboxOption[] = [
  { value: 'IN', label: 'India', keywords: ['IND', 'Bharat'] },
  { value: 'ID', label: 'Indonesia', keywords: ['IDN'] },
  { value: 'US', label: 'United States', keywords: ['USA', 'America'] },
  { value: 'CI', label: "Côte d'Ivoire", keywords: ['CIV', 'Ivory Coast'] },
  { value: 'DE', label: 'Germany', description: 'Europe', keywords: ['DEU', 'Deutschland'] },
]

function Harness({
  initial = '',
  pinnedValues,
  onValue,
  onSubmit,
}: {
  initial?: string
  pinnedValues?: readonly string[]
  onValue?: (value: string) => void
  onSubmit?: () => void
}) {
  const [value, setValue] = useState(initial)
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit?.()
      }}
    >
      <Combobox
        label="Country"
        options={OPTIONS}
        value={value}
        onChange={(next) => {
          setValue(next)
          onValue?.(next)
        }}
        {...(pinnedValues === undefined ? {} : { pinnedValues })}
      />
      <button type="submit">Submit</button>
    </form>
  )
}

function renderCombobox(props: Parameters<typeof Harness>[0] = {}) {
  return render(
    <MemoryRouter>
      <Harness {...props} />
      <button type="button">outside</button>
    </MemoryRouter>,
  )
}

const field = () => screen.getByRole('combobox', { name: 'Country' })

describe('Combobox', () => {
  it('starts closed and announces its state', () => {
    renderCombobox()

    expect(field()).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('is reachable by its label', () => {
    renderCombobox()

    expect(screen.getByLabelText('Country')).toBe(field())
  })

  it('opens on click and lists every option', async () => {
    const user = userEvent.setup()
    renderCombobox()

    await user.click(field())

    expect(field()).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getAllByRole('option')).toHaveLength(OPTIONS.length)
  })

  it('renders cleanly from an empty value', () => {
    // The ProfilePage fixture has country_code: null.
    renderCombobox()

    expect(field()).toHaveValue('')
  })

  it('shows an off-list value as itself rather than a blank field', () => {
    // The API only checks ^[A-Za-z]{2}$ and resume autofill can write a code
    // that is not in the list. Rendering nothing would look like data loss.
    renderCombobox({ initial: 'ZZ' })

    expect(field()).toHaveValue('ZZ')
  })

  describe('keyboard', () => {
    it('does not submit the enclosing form on Enter', async () => {
      // The pickers sit inside ProfilePage's <form>. Without preventDefault,
      // Enter-to-choose-a-country saves the whole section instead.
      const user = userEvent.setup()
      const onSubmit = vi.fn()
      const onValue = vi.fn()
      renderCombobox({ onSubmit, onValue })

      await user.click(field())
      await user.keyboard('{ArrowDown}{Enter}')

      expect(onSubmit).not.toHaveBeenCalled()
      expect(onValue).toHaveBeenCalledWith('IN')
    })

    it('moves aria-activedescendant, not DOM focus', async () => {
      // The whole point of the pattern: focus stays on the input so typing
      // keeps working. Moving focus onto an option is the classic rewrite that
      // silently breaks the component.
      const user = userEvent.setup()
      renderCombobox()

      await user.click(field())
      await user.keyboard('{ArrowDown}')

      const first = screen.getAllByRole('option')[0]!
      expect(field()).toHaveFocus()
      expect(field()).toHaveAttribute('aria-activedescendant', first.id)
    })

    it('wraps around at both ends', async () => {
      const user = userEvent.setup()
      renderCombobox()
      await user.click(field())

      const options = () => screen.getAllByRole('option')

      // Past the last option, back to the first.
      await user.keyboard('{ArrowDown}'.repeat(OPTIONS.length + 1))
      expect(field()).toHaveAttribute('aria-activedescendant', options()[0]!.id)

      // Before the first, round to the last.
      await user.keyboard('{ArrowUp}')
      expect(field()).toHaveAttribute(
        'aria-activedescendant',
        options()[OPTIONS.length - 1]!.id,
      )
    })

    it('Home and End jump to the ends', async () => {
      const user = userEvent.setup()
      renderCombobox()
      await user.click(field())

      await user.keyboard('{End}')
      expect(field()).toHaveAttribute(
        'aria-activedescendant',
        screen.getAllByRole('option')[OPTIONS.length - 1]!.id,
      )

      await user.keyboard('{Home}')
      expect(field()).toHaveAttribute(
        'aria-activedescendant',
        screen.getAllByRole('option')[0]!.id,
      )
    })

    it('Escape closes and keeps the value, reverting typed text', async () => {
      // A second Escape clearing the selection is allowed by APG and skipped
      // deliberately: people press Escape to dismiss, and losing the stored
      // country as a side effect is surprising.
      const user = userEvent.setup()
      const onValue = vi.fn()
      renderCombobox({ initial: 'IN', onValue })

      await user.click(field())
      await user.type(field(), 'germ')
      await user.keyboard('{Escape}')

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
      expect(field()).toHaveValue('India')
      expect(onValue).not.toHaveBeenCalled()
    })

    it('Tab closes without committing the highlight', async () => {
      // Tabbing past a picker and finding it chose something is worse than
      // requiring an explicit Enter.
      const user = userEvent.setup()
      const onValue = vi.fn()
      renderCombobox({ onValue })

      await user.click(field())
      await user.keyboard('{ArrowDown}')
      await user.tab()

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
      expect(onValue).not.toHaveBeenCalled()
    })
  })

  describe('search', () => {
    it('filters as you type', async () => {
      const user = userEvent.setup()
      renderCombobox()

      await user.type(field(), 'germ')

      expect(screen.getAllByRole('option')).toHaveLength(1)
      expect(screen.getByRole('option', { name: /Germany/ })).toBeInTheDocument()
    })

    it('ranks an exact code match first', async () => {
      // "IN" is India, not Indonesia, even though both labels start with "In".
      const user = userEvent.setup()
      renderCombobox()

      await user.type(field(), 'IN')

      expect(screen.getAllByRole('option')[0]!).toHaveTextContent('India')
    })

    it('ignores diacritics', async () => {
      const user = userEvent.setup()
      renderCombobox()

      await user.type(field(), 'cote')

      expect(screen.getByRole('option', { name: /Ivoire/ })).toBeInTheDocument()
    })

    it('matches undisplayed keywords', async () => {
      const user = userEvent.setup()
      renderCombobox()

      await user.type(field(), 'Deutschland')

      expect(screen.getByRole('option', { name: /Germany/ })).toBeInTheDocument()
    })

    it('says so when nothing matches', async () => {
      const user = userEvent.setup()
      renderCombobox()

      await user.type(field(), 'zzzz')

      expect(screen.queryAllByRole('option')).toHaveLength(0)
      expect(screen.getByText('No matches')).toBeInTheDocument()
    })
  })

  describe('committing', () => {
    it('stores the value and displays the label', async () => {
      const user = userEvent.setup()
      const onValue = vi.fn()
      renderCombobox({ onValue })

      await user.click(field())
      await user.click(screen.getByRole('option', { name: /Germany/ }))

      expect(onValue).toHaveBeenCalledWith('DE')
      expect(field()).toHaveValue('Germany')
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    })

    it('marks the current value as selected', async () => {
      const user = userEvent.setup()
      renderCombobox({ initial: 'DE' })

      await user.click(field())

      expect(screen.getByRole('option', { name: /Germany/ })).toHaveAttribute(
        'aria-selected',
        'true',
      )
      expect(screen.getByRole('option', { name: /India/ })).toHaveAttribute(
        'aria-selected',
        'false',
      )
    })

    it('clears through a button that is not named "Save"', async () => {
      // ProfilePage.test.tsx indexes getAllByRole('button', { name: 'Save' })
      // positionally, so a picker must never add one.
      const user = userEvent.setup()
      const onValue = vi.fn()
      renderCombobox({ initial: 'IN', onValue })

      await user.click(screen.getByRole('button', { name: 'Clear Country' }))

      expect(onValue).toHaveBeenCalledWith('')
      expect(field()).toHaveValue('')
      expect(screen.queryAllByRole('button', { name: 'Save' })).toHaveLength(0)
    })

    it('offers no clear button when nothing is selected', () => {
      renderCombobox()

      expect(screen.queryByRole('button', { name: 'Clear Country' })).not.toBeInTheDocument()
    })

    it('reverts typed text when pointing outside', async () => {
      const user = userEvent.setup()
      const onValue = vi.fn()
      renderCombobox({ initial: 'IN', onValue })

      await user.type(field(), 'germ')
      await user.click(screen.getByRole('button', { name: 'outside' }))

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
      expect(field()).toHaveValue('India')
      expect(onValue).not.toHaveBeenCalled()
    })
  })

  describe('pinned values', () => {
    it('groups them ahead of the rest while the query is empty', async () => {
      const user = userEvent.setup()
      renderCombobox({ pinnedValues: ['US', 'DE'] })

      await user.click(field())

      const groups = screen.getAllByRole('group')
      expect(groups).toHaveLength(2)
      expect(groups[0]!).toHaveAccessibleName('Common')
      // Pinned options come first in the flat order, so ArrowDown reaches them
      // before anything else.
      expect(screen.getAllByRole('option')[0]!).toHaveTextContent('United States')
    })

    it('drops the grouping once the user types', async () => {
      // Pinning during a search would hide matches behind a heading rather than
      // ranking them.
      const user = userEvent.setup()
      renderCombobox({ pinnedValues: ['US', 'DE'] })

      await user.type(field(), 'ind')

      expect(screen.queryAllByRole('group')).toHaveLength(0)
      expect(screen.getAllByRole('option')[0]!).toHaveTextContent('India')
    })
  })
})
