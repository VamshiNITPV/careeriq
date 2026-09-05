import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { MonthPicker } from './MonthPicker'

/**
 * The enclosing <form> is load-bearing, not scenery: these pickers live inside
 * CareerSection's form, and "Enter picks a month without submitting the section"
 * is only testable with something to submit.
 */
function Harness({
  initial = '',
  onValue,
  onSubmit,
}: {
  initial?: string
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
      <MonthPicker
        label="Started"
        value={value}
        onChange={(next) => {
          setValue(next)
          onValue?.(next)
        }}
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

const monthSegment = () => screen.getByRole('button', { name: 'Started month' })
const yearSegment = () => screen.getByRole('button', { name: 'Started year' })

/** Computed, never hardcoded — otherwise this suite expires. */
const THIS_YEAR = new Date().getFullYear()

describe('MonthPicker', () => {
  it('reads MM / YYYY when nothing is chosen', () => {
    // The whole point of replacing <input type="month">, which rendered this
    // state as "-------- ----".
    renderPicker()

    expect(monthSegment()).toHaveTextContent('MM')
    expect(yearSegment()).toHaveTextContent('YYYY')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('splits a value into its two segments', () => {
    renderPicker({ initial: '2023-06' })

    expect(monthSegment()).toHaveTextContent('06')
    expect(yearSegment()).toHaveTextContent('2023')
  })

  it('opens on the current year when nothing is chosen', async () => {
    const user = userEvent.setup()
    renderPicker()

    await user.click(yearSegment())

    const list = screen.getByRole('listbox')
    const current = screen.getByRole('option', { name: String(THIS_YEAR) })
    expect(list).toHaveAttribute('aria-activedescendant', current.id)
  })

  it('commits nothing until a month is picked', async () => {
    // One rule: a year advances, a month commits. Anything else means the same
    // gesture sometimes closes the popover and sometimes does not.
    const user = userEvent.setup()
    const onValue = vi.fn()
    renderPicker({ onValue })

    await user.click(yearSegment())
    await user.click(screen.getByRole('option', { name: '2021' }))

    expect(onValue).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Back to years' })).toHaveTextContent('2021')

    await user.click(screen.getByRole('option', { name: 'Mar' }))

    expect(onValue).toHaveBeenCalledExactlyOnceWith('2021-03')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(monthSegment()).toHaveTextContent('03')
    expect(yearSegment()).toHaveTextContent('2021')
  })

  it('goes straight to months when a value already exists', async () => {
    const user = userEvent.setup()
    renderPicker({ initial: '2023-06' })

    await user.click(monthSegment())

    expect(screen.getByRole('option', { name: 'Jun' })).toHaveAttribute('aria-selected', 'true')
  })

  it('asks for a year first when the field is empty', async () => {
    // A month with no year is not representable, and arming the current year
    // silently would write a year the user never chose.
    const user = userEvent.setup()
    renderPicker()

    await user.click(monthSegment())

    expect(screen.getByRole('option', { name: String(THIS_YEAR) })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Jun' })).not.toBeInTheDocument()
  })

  it('offers years ahead of today, for things that expire', async () => {
    const user = userEvent.setup()
    renderPicker()

    await user.click(yearSegment())

    expect(screen.getByRole('option', { name: String(THIS_YEAR + 1) })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: String(THIS_YEAR + 4) })).toBeInTheDocument()
    // Not unbounded — a date picker offering the year 2200 is noise.
    expect(screen.queryByRole('option', { name: String(THIS_YEAR + 30) })).not.toBeInTheDocument()
  })

  it('lists a stored year that falls outside the usual range', async () => {
    // Otherwise editing an old entry shows a list its own value is missing
    // from, and the first tap silently loses it.
    const user = userEvent.setup()
    renderPicker({ initial: '1958-03' })

    await user.click(yearSegment())

    expect(screen.getByRole('option', { name: '1958' })).toHaveAttribute('aria-selected', 'true')
  })

  it('picks with the keyboard without submitting the form', async () => {
    // These live inside CareerSection's <form>. Without preventDefault, Enter
    // to choose a month saves the whole section instead.
    const user = userEvent.setup()
    const onValue = vi.fn()
    const onSubmit = vi.fn()
    renderPicker({ initial: '2023-06', onValue, onSubmit })

    await user.click(monthSegment())
    await user.keyboard('{Enter}')

    expect(onValue).toHaveBeenCalledExactlyOnceWith('2023-06')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('moves one across and a whole row down', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    renderPicker({ initial: '2023-01', onValue })

    await user.click(monthSegment())
    // Jan → Feb across, then Feb → May down a row of three.
    await user.keyboard('{ArrowRight}{ArrowDown}{Enter}')

    expect(onValue).toHaveBeenCalledExactlyOnceWith('2023-05')
  })

  it('stops at the edges rather than wrapping', async () => {
    // Wrap-around in a grid throws the highlight diagonally across the popover
    // and reads as a bug. comboboxCore wraps because its list is 1-D.
    const user = userEvent.setup()
    const onValue = vi.fn()
    renderPicker({ initial: '2023-01', onValue })

    await user.click(monthSegment())
    await user.keyboard('{ArrowUp}{ArrowUp}{ArrowLeft}{Enter}')

    expect(onValue).toHaveBeenCalledExactlyOnceWith('2023-01')
  })

  it('jumps to the ends', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    renderPicker({ initial: '2023-01', onValue })

    await user.click(monthSegment())
    await user.keyboard('{End}{Enter}')

    expect(onValue).toHaveBeenCalledExactlyOnceWith('2023-12')
  })

  it('keeps the value when dismissed with Escape', async () => {
    // Clearing the selection as a side effect of closing surprises people who
    // only meant to shut the popover.
    const user = userEvent.setup()
    const onValue = vi.fn()
    renderPicker({ initial: '2023-06', onValue })

    await user.click(monthSegment())
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(onValue).not.toHaveBeenCalled()
    expect(monthSegment()).toHaveTextContent('06')
    expect(monthSegment()).toHaveFocus()
  })

  it('closes when a pointer lands outside it', async () => {
    const user = userEvent.setup()
    renderPicker()

    await user.click(yearSegment())
    expect(screen.getByRole('listbox')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'outside' }))

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('does not trap Tab', async () => {
    const user = userEvent.setup()
    renderPicker({ initial: '2023-06' })

    await user.click(monthSegment())
    await user.tab()

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    // Focus returned to the opening segment, so the browser computed the next
    // stop from there rather than from the vanished list.
    expect(yearSegment()).toHaveFocus()
  })

  it('can be emptied again', async () => {
    // <input type="month"> supplied a native clear. Without a replacement, a
    // certification's "Expires" could never be unset.
    const user = userEvent.setup()
    const onValue = vi.fn()
    renderPicker({ initial: '2023-06', onValue })

    await user.click(screen.getByRole('button', { name: 'Clear Started' }))

    expect(onValue).toHaveBeenCalledExactlyOnceWith('')
    expect(monthSegment()).toHaveTextContent('MM')
    expect(yearSegment()).toHaveTextContent('YYYY')
  })

  it('has no clear button while it is empty', () => {
    renderPicker()

    expect(screen.queryByRole('button', { name: 'Clear Started' })).not.toBeInTheDocument()
  })

  it('can be walked back from months to years', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    renderPicker({ initial: '2023-06', onValue })

    await user.click(monthSegment())
    await user.click(screen.getByRole('button', { name: 'Back to years' }))
    await user.click(screen.getByRole('option', { name: '2019' }))
    await user.click(screen.getByRole('option', { name: 'Jun' }))

    expect(onValue).toHaveBeenCalledExactlyOnceWith('2019-06')
  })
})
