import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { usePopoverDismiss } from '@/components/ui/popoverDismiss'
import { cn } from '@/utils/cn'

/**
 * A month-and-year picker: MM / YYYY, and nothing finer.
 *
 * It replaces `<input type="month">`, which rendered an empty value as
 * "-------- ----" and opened a full day-by-day calendar. The day was the
 * problem: every date this fills is month precision — the resume said "Jan
 * 2020" and the parser forces day 1 — so a day picker invites the user to state
 * a precision the source never had.
 *
 * The label/hint/error contract is Input.tsx's, field for field, so this sits in
 * a form beside plain Inputs without looking like a different species.
 *
 * There is deliberately no `...rest` spread of InputHTMLAttributes, for the
 * reason Combobox.tsx gives: value/onChange here are not the native ones, and
 * spreading would let a caller pass a native onChange that silently shadows the
 * picker's.
 */

interface MonthPickerProps {
  label: string
  /** "YYYY-MM", or '' for nothing chosen — the shape `<input type="month">` gave. */
  value: string
  onChange: (value: string) => void
  error?: string | undefined
  hint?: string | undefined
  // `| undefined` throughout, not bare optionals: exactOptionalPropertyTypes is
  // on, and CareerSection spreads a `common` object whose `required` is
  // `boolean | undefined`.
  required?: boolean | undefined
  disabled?: boolean | undefined
  /** Oldest selectable year. Defaults to this year minus YEARS_BACK. */
  minYear?: number | undefined
  /** Newest selectable year. Defaults to this year plus YEARS_AHEAD. */
  maxYear?: number | undefined
  className?: string | undefined
}

/**
 * A certification's "Expires" and an in-progress degree's "Finish" are
 * legitimately in the future, so the list runs ahead of today. Six years covers
 * a four-year degree begun this year, with slack.
 */
const YEARS_AHEAD = 6
/** A working life plus schooling: someone of seventy left school ~55 years ago. */
const YEARS_BACK = 60

/** Three columns in both panes, so the popover never changes width. */
const COLUMNS = 3

/**
 * Built with the same local-midnight construction as formatMonth in
 * types/career.ts, so the popover and the summary line under each entry always
 * agree on whether June is "Jun" or "juin".
 */
const MONTH_LABELS = Array.from({ length: 12 }, (_, index) =>
  new Date(2000, index, 1).toLocaleDateString(undefined, { month: 'short' }),
)

interface ParsedMonth {
  year: number
  /** 1-12. */
  month: number
}

function parseMonth(value: string): ParsedMonth | null {
  const match = /^(\d{4})-(\d{2})/.exec(value)
  if (match === null) return null
  const [, rawYear, rawMonth] = match
  if (rawYear === undefined || rawMonth === undefined) return null
  const month = Number(rawMonth)
  if (month < 1 || month > 12) return null
  return { year: Number(rawYear), month }
}

function clamp(value: number, count: number): number {
  return Math.min(Math.max(value, 0), count - 1)
}

/**
 * Full literal class strings, never interpolated names. Tailwind v4 scans source
 * text and emits no CSS at all for a computed class, so a `bg-${x}-50` highlight
 * would simply not render.
 */
function segmentClass(filled: boolean): string {
  const base =
    'rounded px-1 text-sm tabular-nums focus:outline-none ' +
    'focus-visible:ring-2 focus-visible:ring-indigo-600 disabled:cursor-not-allowed'
  return filled ? `${base} text-slate-900` : `${base} text-slate-400`
}

function cellClass(highlighted: boolean, selected: boolean): string {
  const base = 'cursor-pointer rounded-md px-2 py-2 text-center text-sm tabular-nums'
  const tone = highlighted ? 'bg-indigo-50 text-indigo-900' : 'text-slate-700'
  return `${base} ${selected ? 'font-semibold' : ''} ${tone}`
}

export function MonthPicker({
  label,
  value,
  onChange,
  error,
  hint,
  required,
  disabled,
  minYear,
  maxYear,
  className,
}: MonthPickerProps) {
  const id = useId()
  const labelId = `${id}-label`
  const errorId = `${id}-error`
  const hintId = `${id}-hint`
  const paneId = `${id}-pane`
  const cellId = useCallback((index: number) => `${id}-cell-${index}`, [id])

  const selected = parseMonth(value)

  // null is closed. Otherwise which of the two panes is showing.
  const [pane, setPane] = useState<'year' | 'month' | null>(null)
  // The year a month is about to be attached to. Chosen but not yet committed:
  // nothing reaches onChange until a month is picked.
  const [armedYear, setArmedYear] = useState(() => selected?.year ?? new Date().getFullYear())
  const [highlighted, setHighlighted] = useState(-1)

  const monthRef = useRef<HTMLButtonElement>(null)
  const yearRef = useRef<HTMLButtonElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  // Which segment opened the popover, so Escape and Tab hand focus back to it.
  const openerRef = useRef<'year' | 'month'>('year')

  const close = useCallback(() => {
    setPane(null)
    setHighlighted(-1)
  }, [])

  const rootRef = usePopoverDismiss<HTMLDivElement>({
    open: pane !== null,
    onOutsidePointer: close,
    onRouteChange: close,
  })

  const thisYear = new Date().getFullYear()
  const first = Math.min(minYear ?? thisYear - YEARS_BACK, selected?.year ?? Number.MAX_SAFE_INTEGER)
  const last = Math.max(maxYear ?? thisYear + YEARS_AHEAD, selected?.year ?? Number.MIN_SAFE_INTEGER)
  // Newest first, so the future years sit nearest the field. A stored year
  // outside the default range is folded in above: editing an entry from 1958
  // must not show a list its own value is missing from, where the first tap
  // would silently lose it.
  const years = Array.from({ length: last - first + 1 }, (_, index) => last - index)

  const count = pane === 'month' ? 12 : years.length

  // Focus is applied in an effect rather than straight after setPane: the pane
  // does not exist in the DOM until React has committed the render, so focusing
  // any earlier is a no-op. Unlike requestAnimationFrame it is deterministic
  // under test.
  useEffect(() => {
    if (pane === null) return
    listRef.current?.focus()
  }, [pane])

  useEffect(() => {
    if (pane !== 'year' || highlighted < 0) return
    const list = listRef.current
    // getElementById, not querySelector: React 19's useId produces ids like
    // «r3». Those are legal ids but not legal CSS identifiers, so a selector
    // lookup throws SyntaxError at runtime.
    const cell = document.getElementById(cellId(highlighted))
    if (list === null || cell === null) return
    // The list's own scrollTop, not scrollIntoView: that walks up to the page
    // scroller and would jump the whole form sideways as the popover opens.
    // The month pane never scrolls, so it is excluded above.
    list.scrollTop = cell.offsetTop - list.clientHeight / 2 + cell.clientHeight / 2
  }, [pane, highlighted, cellId])

  function openYearPane() {
    openerRef.current = 'year'
    const year = selected?.year ?? thisYear
    setArmedYear(year)
    setPane('year')
    setHighlighted(Math.max(years.indexOf(year), 0))
  }

  function openMonthPane() {
    openerRef.current = 'month'
    // With no value there is no year to attach a month to, and quietly arming
    // the current year would write a year the user never chose into a field
    // that feeds match scoring. One extra tap is the honest trade.
    if (selected === null) {
      openYearPane()
      return
    }
    setArmedYear(selected.year)
    setPane('month')
    setHighlighted(selected.month - 1)
  }

  function chooseYear(index: number) {
    const year = years[index]
    if (year === undefined) return
    // Deliberately commits nothing. One rule — a month commits, a year does not
    // — beats "sometimes this closes the popover and sometimes it doesn't".
    setArmedYear(year)
    setPane('month')
    setHighlighted(selected === null ? 0 : selected.month - 1)
  }

  function chooseMonth(index: number) {
    onChange(`${String(armedYear).padStart(4, '0')}-${String(index + 1).padStart(2, '0')}`)
    close()
    // The month segment shows what was just decided.
    monthRef.current?.focus()
  }

  function commit(index: number) {
    if (pane === 'year') chooseYear(index)
    else if (pane === 'month') chooseMonth(index)
  }

  function returnFocus() {
    const target = openerRef.current === 'month' ? monthRef.current : yearRef.current
    target?.focus()
  }

  function onListKeyDown(event: KeyboardEvent<HTMLUListElement>) {
    switch (event.key) {
      // Clamped, not wrapped like comboboxCore's 1-D list: wrap-around in a
      // grid throws the highlight diagonally across the popover and reads as a
      // bug rather than as navigation.
      case 'ArrowRight':
        event.preventDefault()
        setHighlighted((current) => clamp(current + 1, count))
        break
      case 'ArrowLeft':
        event.preventDefault()
        setHighlighted((current) => clamp(current - 1, count))
        break
      case 'ArrowDown':
        event.preventDefault()
        setHighlighted((current) => clamp(current + COLUMNS, count))
        break
      case 'ArrowUp':
        event.preventDefault()
        setHighlighted((current) => clamp(current - COLUMNS, count))
        break
      case 'Home':
        event.preventDefault()
        setHighlighted(0)
        break
      case 'End':
        event.preventDefault()
        setHighlighted(count - 1)
        break
      case 'Enter':
      case ' ':
        // preventDefault even with nothing highlighted. These sit inside
        // CareerSection's <form>, so without it Enter-to-pick-a-month submits
        // the whole section. Space would scroll the page.
        event.preventDefault()
        if (highlighted >= 0) commit(highlighted)
        break
      case 'Escape':
        event.preventDefault()
        // Stop it reaching an enclosing dialog — ConfirmDialog is on this same
        // page. Escape closes outright rather than stepping back a pane: "get
        // me out" is what it means. The value is left alone.
        event.stopPropagation()
        close()
        returnFocus()
        break
      case 'Tab':
        // Deliberately NOT trapped and deliberately not committing: focus moves
        // to the opening segment during the keydown, without preventDefault, so
        // the browser computes the next tab stop from there.
        close()
        returnFocus()
        break
      default:
        break
    }
  }

  function onSegmentKeyDown(event: KeyboardEvent<HTMLButtonElement>, open: () => void) {
    // Enter and Space are native button activation and already run onClick.
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      open()
    }
  }

  const cells =
    pane === 'month'
      ? MONTH_LABELS.map((text, index) => ({
          text,
          selected: selected !== null && selected.year === armedYear && selected.month === index + 1,
        }))
      : years.map((year) => ({
          text: String(year),
          selected: selected !== null && selected.year === year,
        }))

  return (
    <div className={className}>
      {/*
        A <span>, not a <label htmlFor>: there are two buttons here and no
        single labelable control to point at. The group below borrows this as
        its accessible name.
      */}
      <span id={labelId} className="block text-sm font-medium text-slate-900">
        {label}
        {required === true && (
          <span className="ml-0.5 text-red-600" aria-hidden="true">
            *
          </span>
        )}
      </span>

      <div
        ref={rootRef}
        role="group"
        aria-labelledby={labelId}
        aria-describedby={
          cn(error !== undefined && errorId, hint !== undefined && hintId) || undefined
        }
        className={cn(
          'relative mt-1.5 flex w-full items-center gap-1 rounded-md border-0 px-3 py-2 shadow-sm',
          'ring-1 ring-inset focus-within:ring-2 focus-within:ring-inset',
          disabled === true && 'cursor-not-allowed bg-slate-50',
          error !== undefined
            ? 'ring-red-400 focus-within:ring-red-600'
            : 'ring-slate-300 focus-within:ring-indigo-600',
        )}
      >
        {/*
          Raw string slicing rather than Intl for the segments: it keeps "06"
          zero-padded for free, and keeps the digits Latin under any machine
          locale. The popover uses month names, where locale is what you want.
        */}
        <button
          ref={monthRef}
          type="button"
          aria-label={`${label} month`}
          aria-haspopup="listbox"
          aria-expanded={pane !== null}
          aria-controls={paneId}
          disabled={disabled}
          onClick={openMonthPane}
          onKeyDown={(event) => onSegmentKeyDown(event, openMonthPane)}
          className={segmentClass(selected !== null)}
        >
          {selected === null ? 'MM' : String(selected.month).padStart(2, '0')}
        </button>

        <span aria-hidden="true" className="text-slate-400">
          /
        </span>

        <button
          ref={yearRef}
          type="button"
          aria-label={`${label} year`}
          aria-haspopup="listbox"
          aria-expanded={pane !== null}
          aria-controls={paneId}
          disabled={disabled}
          onClick={openYearPane}
          onKeyDown={(event) => onSegmentKeyDown(event, openYearPane)}
          className={segmentClass(selected !== null)}
        >
          {selected === null ? 'YYYY' : String(selected.year).padStart(4, '0')}
        </button>

        <span className="ml-auto flex items-center gap-1">
          {/*
            Not optional. <input type="month"> supplied a native clear; without
            a replacement, someone who sets a certification's "Expires" has no
            way back to no date at all.
          */}
          {value !== '' && disabled !== true && (
            <button
              type="button"
              // Never named "Save": ProfilePage.test.tsx indexes into
              // getAllByRole('button', { name: 'Save' }) positionally.
              aria-label={`Clear ${label}`}
              onClick={() => {
                onChange('')
                close()
                monthRef.current?.focus()
              }}
              className="rounded p-0.5 text-slate-400 hover:text-slate-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-600"
            >
              <svg viewBox="0 0 20 20" fill="currentColor" className="size-4" aria-hidden="true">
                <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
              </svg>
            </button>
          )}
          <svg
            viewBox="0 0 20 20"
            fill="currentColor"
            className="size-4 text-slate-400"
            aria-hidden="true"
          >
            <path d="M5.75 2a.75.75 0 0 1 .75.75V4h7V2.75a.75.75 0 0 1 1.5 0V4h.25A2.25 2.25 0 0 1 17.5 6.25v9A2.25 2.25 0 0 1 15.25 17.5H4.75A2.25 2.25 0 0 1 2.5 15.25v-9A2.25 2.25 0 0 1 4.75 4H5V2.75A.75.75 0 0 1 5.75 2ZM4 8v7.25c0 .414.336.75.75.75h10.5a.75.75 0 0 0 .75-.75V8H4Z" />
          </svg>
        </span>

        {pane !== null && (
          <div
            id={paneId}
            className={cn(
              'absolute top-full left-0 z-30 mt-1 w-full min-w-60 rounded-md',
              'border border-slate-200 bg-white p-2 shadow-lg',
            )}
          >
            {pane === 'year' ? (
              <p className="px-2 pb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
                Choose a year
              </p>
            ) : (
              // The only way back, and it doubles as the reminder of which year
              // this month is being attached to.
              <button
                type="button"
                aria-label="Back to years"
                onClick={openYearPane}
                className="mb-1 flex w-full items-center gap-1 rounded px-2 py-1 text-sm font-semibold text-slate-700 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-600"
              >
                <span aria-hidden="true">‹</span>
                {armedYear}
              </button>
            )}

            <ul
              ref={listRef}
              role="listbox"
              tabIndex={-1}
              aria-label={pane === 'year' ? `${label} year` : `${label} month`}
              aria-activedescendant={highlighted >= 0 ? cellId(highlighted) : undefined}
              onKeyDown={onListKeyDown}
              // Keeps the list focused when a cell is clicked. Cells are not
              // focusable, so without this the browser blurs it mid-click.
              onMouseDown={(event) => event.preventDefault()}
              className={cn(
                // `relative` makes this the offsetParent of its cells, which is
                // what the scroll effect above measures against.
                'relative grid grid-cols-3 gap-1 focus:outline-none',
                pane === 'year' && 'max-h-60 overflow-auto',
              )}
            >
              {cells.map((cell, index) => (
                <li
                  key={cell.text}
                  id={cellId(index)}
                  role="option"
                  aria-selected={cell.selected}
                  onClick={() => commit(index)}
                  onMouseEnter={() => setHighlighted(index)}
                  className={cellClass(highlighted === index, cell.selected)}
                >
                  {cell.text}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {hint !== undefined && error === undefined && (
        <p id={hintId} className="mt-1.5 text-sm text-slate-500">
          {hint}
        </p>
      )}
      {error !== undefined && (
        <p id={errorId} className="mt-1.5 text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  )
}
