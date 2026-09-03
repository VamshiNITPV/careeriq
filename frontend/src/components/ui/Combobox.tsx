import { useId, useMemo, useState, type FocusEvent } from 'react'
import { cn } from '@/utils/cn'
import {
  buildIndex,
  emptyMessageClass,
  groupLabelClass,
  listboxClass,
  optionClass,
  partitionPinned,
  searchOptions,
  useComboboxNav,
  type ComboboxOption,
} from './comboboxCore'

/**
 * A single-select searchable picker.
 *
 * The label/hint/error contract is Input.tsx's, field for field, so a Combobox
 * sits in a form beside plain Inputs without looking or behaving like a
 * different species.
 *
 * There is deliberately no `...rest` spread of InputHTMLAttributes. Input can
 * spread because its value/onChange are the native ones; here they are not, and
 * spreading would let a caller pass a native onChange that silently shadows the
 * picker's. The attributes actually needed are enumerated instead.
 */

interface ComboboxProps {
  label: string
  options: readonly ComboboxOption[]
  /** The stored value. '' means nothing selected. */
  value: string
  onChange: (value: string) => void
  error?: string | undefined
  hint?: string | undefined
  placeholder?: string | undefined
  required?: boolean
  disabled?: boolean
  /**
   * Values floated into their own group ahead of the rest, but only while the
   * query is empty.
   */
  pinnedValues?: readonly string[]
  pinnedLabel?: string
  restLabel?: string
  className?: string
}

export function Combobox({
  label,
  options,
  value,
  onChange,
  error,
  hint,
  placeholder,
  required,
  disabled,
  pinnedValues,
  pinnedLabel = 'Common',
  restLabel = 'All',
  className,
}: ComboboxProps) {
  const id = useId()
  const errorId = `${id}-error`
  const hintId = `${id}-hint`

  // null means "not typing" — the field shows the selected label. Any string,
  // including '', means the user is searching.
  const [query, setQuery] = useState<string | null>(null)

  const index = useMemo(() => buildIndex(options), [options])
  const visible = useMemo(() => searchOptions(index, query ?? ''), [index, query])

  // An off-list value renders as itself rather than as a blank field. The
  // backend only checks `^[A-Za-z]{2}$` for a country code and resume autofill
  // can write one that is not in the list; showing nothing would look like data
  // loss and invite the user to "fix" it.
  const selectedLabel = options.find((option) => option.value === value)?.label ?? value

  // Pinning is pointless once the user is searching: it would hide matches
  // behind a heading rather than ranking them.
  const searching = query !== null && query.trim() !== ''
  const { flat, groups } = searching
    ? { flat: visible, groups: [{ label: null, options: visible, offset: 0 }] }
    : partitionPinned(visible, pinnedValues, pinnedLabel, restLabel)

  const selectedIndex = flat.findIndex((option) => option.value === value)

  const nav = useComboboxNav({
    count: flat.length,
    initialHighlight: selectedIndex >= 0 ? selectedIndex : 0,
    onCommit: (i) => commit(i),
    onDismiss: () => setQuery(null),
  })

  function commit(i: number) {
    const option = flat[i]
    if (option === undefined) return
    onChange(option.value)
    setQuery(null)
    nav.setOpen(false)
    nav.setHighlighted(-1)
  }

  function onBlur(event: FocusEvent<HTMLDivElement>) {
    // relatedTarget inside the root means focus moved to the clear button, not
    // out of the picker. Options are not focusable and the listbox suppresses
    // mousedown, so clicking one never reaches here.
    if (nav.rootRef.current?.contains(event.relatedTarget)) return
    nav.setOpen(false)
    nav.setHighlighted(-1)
    // Typed text that was never committed reverts to the selected label rather
    // than being left in the field looking like a value.
    setQuery(null)
  }

  const activeId =
    nav.open && nav.highlighted >= 0 && nav.highlighted < flat.length
      ? nav.optionId(nav.highlighted)
      : undefined

  return (
    <div className={className}>
      <label htmlFor={id} className="block text-sm font-medium text-slate-900">
        {label}
        {required === true && (
          <span className="ml-0.5 text-red-600" aria-hidden="true">
            *
          </span>
        )}
      </label>

      <div className="relative" ref={nav.rootRef} onBlur={onBlur}>
        <input
          id={id}
          ref={nav.inputRef}
          type="text"
          role="combobox"
          aria-expanded={nav.open}
          aria-controls={nav.listboxId}
          aria-autocomplete="list"
          aria-activedescendant={activeId}
          autoComplete="off"
          required={required}
          disabled={disabled}
          placeholder={placeholder}
          value={query ?? selectedLabel}
          aria-invalid={error !== undefined}
          aria-describedby={
            cn(error !== undefined && errorId, hint !== undefined && hintId) || undefined
          }
          onChange={(event) => {
            setQuery(event.target.value)
            nav.setOpen(true)
            nav.setHighlighted(0)
          }}
          onKeyDown={nav.onKeyDown}
          onClick={() => {
            // selectedIndex is -1 when nothing is chosen, which is the point:
            // opening by pointer highlights the current value (so it scrolls
            // into view) but never pre-arms a row the user has not navigated
            // to. Typing sets the highlight to the best match instead.
            if (!nav.open) nav.openAt(selectedIndex)
          }}
          className={cn(
            'mt-1.5 block w-full rounded-md border-0 py-2 pr-16 pl-3 text-slate-900 shadow-sm',
            'ring-1 ring-inset placeholder:text-slate-400',
            'focus:ring-2 focus:ring-inset focus:outline-none',
            'disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500',
            error !== undefined
              ? 'ring-red-400 focus:ring-red-600'
              : 'ring-slate-300 focus:ring-indigo-600',
          )}
        />

        <div className="absolute inset-y-0 right-0 mt-1.5 flex items-center gap-1 pr-2">
          {value !== '' && disabled !== true && (
            <button
              type="button"
              // Never named "Save": ProfilePage.test.tsx indexes into
              // getAllByRole('button', { name: 'Save' }) positionally.
              aria-label={`Clear ${label}`}
              onClick={() => {
                onChange('')
                setQuery(null)
                nav.inputRef.current?.focus()
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
            <path d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" />
          </svg>
        </div>

        {nav.open && (
          <ul
            id={nav.listboxId}
            role="listbox"
            aria-label={label}
            // Keeps the input focused when an option is clicked. Options are not
            // focusable, so without this the browser blurs the input mid-click.
            onMouseDown={(event) => event.preventDefault()}
            className={listboxClass}
          >
            {flat.length === 0 && <li className={emptyMessageClass}>No matches</li>}

            {groups.map((group) => {
              const rows = group.options.map((option, i) => {
                const flatIndex = group.offset + i
                const selected = option.value === value
                return (
                  <li
                    key={option.value}
                    id={nav.optionId(flatIndex)}
                    role="option"
                    aria-selected={selected}
                    onClick={() => commit(flatIndex)}
                    onMouseEnter={() => nav.setHighlighted(flatIndex)}
                    className={optionClass(nav.highlighted === flatIndex, selected, false)}
                  >
                    <span className="truncate">{option.label}</span>
                    {option.description !== undefined && (
                      <span className="shrink-0 text-xs text-slate-500">{option.description}</span>
                    )}
                  </li>
                )
              })

              // A bare <div> or <hr> as a direct child of role="listbox" is
              // invalid and some screen readers drop everything after it, so a
              // heading has to come with role="group".
              return group.label === null ? (
                rows
              ) : (
                <li key={group.label} role="group" aria-label={group.label}>
                  <div className={groupLabelClass}>{group.label}</div>
                  <ul role="presentation">{rows}</ul>
                </li>
              )
            })}
          </ul>
        )}

        {/*
          aria-live with no role attribute. Alert.tsx already owns role="alert"
          and role="status" on this page, and ProfilePage.test.tsx queries for
          exactly one of each — testing-library computes roles from the element
          and its role attribute, not from aria-live, so this stays invisible to
          those queries while still being announced.
        */}
        <span aria-live="polite" className="sr-only">
          {nav.open ? `${flat.length} results` : ''}
        </span>
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
