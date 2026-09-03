import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { MultiCombobox } from './MultiCombobox'
import type { ComboboxOption } from './comboboxCore'

const OPTIONS: readonly ComboboxOption[] = [
  { value: 'Remote', label: 'Remote', description: 'Work from anywhere' },
  { value: 'Bengaluru', label: 'Bengaluru', description: 'Karnataka, India', keywords: ['Bangalore'] },
  { value: 'Pune', label: 'Pune', description: 'Maharashtra, India' },
  { value: 'New York', label: 'New York', description: 'United States' },
  { value: 'Berlin', label: 'Berlin', description: 'Germany' },
]

function Harness({
  initial = [],
  max,
  onValue,
  onSubmit,
}: {
  initial?: string[]
  max?: number
  onValue?: (value: string[]) => void
  onSubmit?: () => void
}) {
  const [value, setValue] = useState<string[]>(initial)
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit?.()
      }}
    >
      <MultiCombobox
        label="Preferred locations"
        options={OPTIONS}
        value={value}
        onChange={(next) => {
          setValue(next)
          onValue?.(next)
        }}
        allowCustom
        {...(max === undefined ? {} : { max })}
      />
      <button type="submit">Submit</button>
    </form>
  )
}

function renderPicker(props: Parameters<typeof Harness>[0] = {}) {
  return render(
    <MemoryRouter>
      <Harness {...props} />
      <button type="button">outside</button>
    </MemoryRouter>,
  )
}

const field = () => screen.getByRole('combobox', { name: 'Preferred locations' })

describe('MultiCombobox', () => {
  it('announces itself as multi-selectable', async () => {
    const user = userEvent.setup()
    renderPicker()

    await user.click(field())

    expect(screen.getByRole('listbox')).toHaveAttribute('aria-multiselectable', 'true')
  })

  it('renders cleanly from an empty list', () => {
    renderPicker()

    expect(field()).toHaveValue('')
    expect(screen.queryAllByRole('button', { name: /^Remove/ })).toHaveLength(0)
  })

  it('stays open and clears the query after a selection', async () => {
    // Picking one location almost always means picking another.
    const user = userEvent.setup()
    renderPicker()

    await user.type(field(), 'beng')
    await user.keyboard('{Enter}')

    expect(screen.getByRole('listbox')).toBeInTheDocument()
    expect(field()).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Remove Bengaluru' })).toBeInTheDocument()
  })

  it('toggles a selected option back off', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    renderPicker({ initial: ['Pune'], onValue })

    await user.click(field())
    await user.click(screen.getByRole('option', { name: /Pune/ }))

    expect(onValue).toHaveBeenCalledWith([])
  })

  it('flips aria-selected on the chosen rows', async () => {
    const user = userEvent.setup()
    renderPicker({ initial: ['Pune'] })

    await user.click(field())

    expect(screen.getByRole('option', { name: /Pune/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('option', { name: /Berlin/ })).toHaveAttribute('aria-selected', 'false')
  })

  it('removes a chip through its own button', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    renderPicker({ initial: ['Pune', 'Berlin'], onValue })

    await user.click(screen.getByRole('button', { name: 'Remove Pune' }))

    expect(onValue).toHaveBeenCalledWith(['Berlin'])
  })

  it('shows an off-list value as itself', () => {
    // Seeded chips are values, not options. Rewriting a stored "Bangalore" to
    // "Bengaluru" would make an untouched form save a changed array.
    renderPicker({ initial: ['Bangalore'] })

    expect(screen.getByRole('button', { name: 'Remove Bangalore' })).toBeInTheDocument()
  })

  describe('keyboard', () => {
    it('does not submit the enclosing form on Enter', async () => {
      const user = userEvent.setup()
      const onSubmit = vi.fn()
      renderPicker({ onSubmit })

      await user.type(field(), 'pune')
      await user.keyboard('{Enter}')

      expect(onSubmit).not.toHaveBeenCalled()
      expect(screen.getByRole('button', { name: 'Remove Pune' })).toBeInTheDocument()
    })

    it('Backspace on an empty query removes the last chip', async () => {
      const user = userEvent.setup()
      const onValue = vi.fn()
      renderPicker({ initial: ['Pune', 'Berlin'], onValue })

      await user.click(field())
      await user.keyboard('{Backspace}')

      expect(onValue).toHaveBeenCalledWith(['Pune'])
    })

    it('Backspace with text in the field edits the text instead', async () => {
      const user = userEvent.setup()
      const onValue = vi.fn()
      renderPicker({ initial: ['Pune'], onValue })

      await user.type(field(), 'ber')
      await user.keyboard('{Backspace}')

      expect(field()).toHaveValue('be')
      expect(onValue).not.toHaveBeenCalled()
    })
  })

  describe('free text', () => {
    it('offers an option row, not a button', async () => {
      // SkillAdder uses a <Button> for this; here it must be role="option" so
      // it inherits arrow navigation and adds nothing to the page's button
      // list, which ProfilePage.test.tsx indexes positionally.
      const user = userEvent.setup()
      renderPicker()

      await user.type(field(), 'Gurugram Sector 44')

      expect(screen.getByRole('option', { name: /Gurugram Sector 44/ })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Gurugram Sector 44/ })).not.toBeInTheDocument()
    })

    it('stores the typed text verbatim', async () => {
      const user = userEvent.setup()
      const onValue = vi.fn()
      renderPicker({ onValue })

      await user.type(field(), 'Gurugram Sector 44')
      await user.keyboard('{Enter}')

      expect(onValue).toHaveBeenCalledWith(['Gurugram Sector 44'])
    })

    it('is not offered for text matching an option label', async () => {
      const user = userEvent.setup()
      renderPicker()

      await user.type(field(), 'berlin')

      expect(screen.queryByRole('option', { name: /Use/ })).not.toBeInTheDocument()
    })

    it('is not offered for text matching a keyword', async () => {
      // Otherwise typing "bangalore" would offer both Bengaluru and a
      // near-duplicate of it.
      const user = userEvent.setup()
      renderPicker()

      await user.type(field(), 'Bangalore')

      expect(screen.queryByRole('option', { name: /Use/ })).not.toBeInTheDocument()
      expect(screen.getByRole('option', { name: /Bengaluru/ })).toBeInTheDocument()
    })

    it('is not offered for text matching an existing chip', async () => {
      // The backend dedupes case-insensitively and keeps the first spelling, so
      // producing a pair here would silently diverge from what comes back.
      const user = userEvent.setup()
      renderPicker({ initial: ['Gurgaon'] })

      await user.type(field(), 'gurgaon')

      expect(screen.queryByRole('option', { name: /Use/ })).not.toBeInTheDocument()
    })

    it('prefers a real match over the typed text', async () => {
      // Typing "bangalore" and hitting Enter stores the canonical spelling.
      const user = userEvent.setup()
      const onValue = vi.fn()
      renderPicker({ onValue })

      await user.type(field(), 'bangalor')
      await user.keyboard('{Enter}')

      expect(onValue).toHaveBeenCalledWith(['Bengaluru'])
    })

    it('is not offered for a single character', async () => {
      const user = userEvent.setup()
      renderPicker()

      await user.type(field(), 'q')

      expect(screen.queryByRole('option', { name: /Use/ })).not.toBeInTheDocument()
    })

    it('is not offered for text past the length cap', async () => {
      // profiles.preferred_locations is ARRAY(Text) and _clean_list has no
      // per-item cap, so this is the only guard against a paste accident.
      const user = userEvent.setup()
      renderPicker()

      await user.type(field(), 'x'.repeat(101))

      expect(screen.queryByRole('option', { name: /Use/ })).not.toBeInTheDocument()
    })
  })

  describe('the cap', () => {
    it('disables unselected options once full', async () => {
      const user = userEvent.setup()
      const onValue = vi.fn()
      renderPicker({ initial: ['Pune', 'Berlin'], max: 2, onValue })

      await user.click(field())

      expect(screen.getByRole('option', { name: /New York/ })).toHaveAttribute(
        'aria-disabled',
        'true',
      )
      // Selected ones stay live, so the user can still deselect their way out.
      expect(screen.getByRole('option', { name: /Pune/ })).not.toHaveAttribute('aria-disabled')

      await user.click(screen.getByRole('option', { name: /New York/ }))
      expect(onValue).not.toHaveBeenCalled()
    })

    it('withdraws the free-text row once full', async () => {
      const user = userEvent.setup()
      renderPicker({ initial: ['Pune', 'Berlin'], max: 2 })

      await user.type(field(), 'Kochi')

      expect(screen.queryByRole('option', { name: /Use/ })).not.toBeInTheDocument()
    })
  })
})
