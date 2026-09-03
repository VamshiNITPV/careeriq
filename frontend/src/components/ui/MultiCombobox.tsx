import { useId, useMemo, useState, type KeyboardEvent } from 'react'
import { cn } from '@/utils/cn'
import { normalizeText } from '@/utils/normalizeText'
import {
  buildIndex,
  emptyMessageClass,
  listboxClass,
  optionClass,
  searchOptions,
  useComboboxNav,
  type ComboboxOption,
} from './comboboxCore'

/**
 * A multi-select searchable picker with chips, optionally accepting values that
 * are not in the list.
 *
 * Separate from Combobox rather than a `multiple` prop on it: after a commit
 * this one stays open and clears the query, its control is a chip well rather
 * than a text field, Backspace means something, and blur clears rather than
 * reverts. A union-typed `value: string | string[]` would also push casts into
 * every call site under this project's exactOptionalPropertyTypes /
 * noUncheckedIndexedAccess settings.
 */

/**
 * The backend's _clean_list strips and dedupes but has no per-item length cap,
 * and the column is ARRAY(Text). This is the only thing standing between a
 * paste accident and a 40 KB array element.
 */
const MAX_ITEM_LENGTH = 100

interface MultiComboboxProps {
  label: string
  options: readonly ComboboxOption[]
  value: readonly string[]
  onChange: (value: string[]) => void
  error?: string | undefined
  hint?: string | undefined
  placeholder?: string | undefined
  required?: boolean
  disabled?: boolean
  /** Offer "Use <typed text>" for anything not in the list. */
  allowCustom?: boolean
  /** Mirrors MAX_LIST_ITEMS in backend/app/schemas/profile.py. */
  max?: number
  className?: string
}

export function MultiCombobox({
  label,
  options,
  value,
  onChange,
  error,
  hint,
  placeholder,
  required,
  disabled,
  allowCustom,
  max = 20,
  className,
}: MultiComboboxProps) {
  const id = useId()
  const errorId = `${id}-error`
  const hintId = `${id}-hint`

  const [query, setQuery] = useState('')

  const index = useMemo(() => buildIndex(options), [options])
  const visible = useMemo(() => searchOptions(index, query), [index, query])

  /** Every searchable form of every option, for the "is this already known?" test. */
  const known = useMemo(() => {
    const set = new Set<string>()
    for (const option of options) {
      set.add(normalizeText(option.label))
      set.add(normalizeText(option.value))
      for (const keyword of option.keywords ?? []) set.add(normalizeText(keyword))
    }
    return set
  }, [options])

  // Selection is compared on the normalised form, mirroring the backend's
  // case-insensitive dedupe. This is what guarantees the chips on screen match
  // what comes back from the server.
  const selected = useMemo(() => new Set(value.map(normalizeText)), [value])
  const full = value.length >= max

  const trimmed = query.trim()
  const canCreate =
    allowCustom === true &&
    trimmed.length >= 2 &&
    trimmed.length <= MAX_ITEM_LENGTH &&
    !full &&
    !known.has(normalizeText(trimmed)) &&
    !selected.has(normalizeText(trimmed))

  // The create row lives at the end of the flat list, so when real matches
  // exist the first one is highlighted and typing "bangalore" + Enter stores
  // the canonical "Bengaluru" rather than the typo. With no matches it is the
  // only row, and is highlighted automatically.
  const count = visible.length + (canCreate ? 1 : 0)

  const nav = useComboboxNav({
    count,
    initialHighlight: 0,
    onCommit: (i) => commit(i),
    onDismiss: () => setQuery(''),
  })

  function add(item: string) {
    if (value.length >= max) return
    if (selected.has(normalizeText(item))) return
    onChange([...value, item])
    setQuery('')
    nav.setHighlighted(0)
  }

  function remove(item: string) {
    const target = normalizeText(item)
    onChange(value.filter((current) => normalizeText(current) !== target))
  }

  function commit(i: number) {
    if (canCreate && i === visible.length) {
      add(trimmed)
      return
    }
    const option = visible[i]
    if (option === undefined) return
    if (selected.has(normalizeText(option.value))) remove(option.value)
    else add(option.value)
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Backspace' && query === '' && value.length > 0) {
      event.preventDefault()
      onChange(value.slice(0, -1))
      return
    }
    nav.onKeyDown(event)
  }

  const activeId =
    nav.open && nav.highlighted >= 0 && nav.highlighted < count
      ? nav.optionId(nav.highlighted)
      : undefined

  /** Chips render seeded values as themselves — see the off-list note below. */
  function labelFor(item: string): string {
    return options.find((option) => option.value === item)?.label ?? item
  }

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

      <div
        className="relative"
        ref={nav.rootRef}
        onBlur={(event) => {
          // Focus moving to a chip's remove button stays inside the picker.
          if (nav.rootRef.current?.contains(event.relatedTarget)) return
          nav.setOpen(false)
          nav.setHighlighted(-1)
          setQuery('')
        }}
      >
        {/*
          The ring sits on the wrapper and the input goes bare, or focusing the
          field draws two rings. focus-within rather than focus, since the thing
          receiving focus is a child.
        */}
        <div
          onClick={() => nav.inputRef.current?.focus()}
          className={cn(
            'mt-1.5 flex w-full flex-wrap items-center gap-1.5 rounded-md border-0 px-2 py-1.5',
            'text-slate-900 shadow-sm ring-1 ring-inset',
            'focus-within:ring-2 focus-within:ring-inset',
            disabled === true && 'cursor-not-allowed bg-slate-50',
            error !== undefined
              ? 'ring-red-400 focus-within:ring-red-600'
              : 'ring-slate-300 focus-within:ring-indigo-600',
          )}
        >
          {value.map((item) => (
            <span
              key={item}
              className="inline-flex items-center gap-1 rounded-full border border-indigo-600 bg-indigo-50 py-1 pr-1 pl-3 text-sm text-indigo-700"
            >
              {labelFor(item)}
              <button
                type="button"
                aria-label={`Remove ${labelFor(item)}`}
                disabled={disabled}
                onClick={(event) => {
                  event.stopPropagation()
                  remove(item)
                }}
                className="rounded-full p-0.5 text-indigo-500 hover:bg-indigo-100 hover:text-indigo-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-600"
              >
                <svg viewBox="0 0 20 20" fill="currentColor" className="size-3.5" aria-hidden="true">
                  <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
                </svg>
              </button>
            </span>
          ))}

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
            required={required && value.length === 0}
            disabled={disabled}
            placeholder={value.length === 0 ? placeholder : undefined}
            value={query}
            aria-invalid={error !== undefined}
            aria-describedby={
              cn(error !== undefined && errorId, hint !== undefined && hintId) || undefined
            }
            onChange={(event) => {
              setQuery(event.target.value)
              nav.setOpen(true)
              nav.setHighlighted(0)
            }}
            onKeyDown={onKeyDown}
            onClick={() => {
              // -1: opening by pointer arms nothing, so a stray Enter cannot
              // add a location the user never looked at. Typing highlights the
              // best match.
              if (!nav.open) nav.openAt(-1)
            }}
            className="min-w-32 flex-1 border-0 bg-transparent p-1 text-slate-900 placeholder:text-slate-400 focus:ring-0 focus:outline-none disabled:cursor-not-allowed"
          />
        </div>

        {nav.open && (
          <ul
            id={nav.listboxId}
            role="listbox"
            aria-label={label}
            aria-multiselectable="true"
            onMouseDown={(event) => event.preventDefault()}
            className={listboxClass}
          >
            {count === 0 && (
              <li className={emptyMessageClass}>
                {full ? `You can add up to ${max}.` : 'No matches'}
              </li>
            )}

            {visible.map((option, i) => {
              const isSelected = selected.has(normalizeText(option.value))
              const blocked = full && !isSelected
              return (
                <li
                  key={option.value}
                  id={nav.optionId(i)}
                  role="option"
                  aria-selected={isSelected}
                  aria-disabled={blocked || undefined}
                  onClick={() => {
                    if (!blocked) commit(i)
                  }}
                  onMouseEnter={() => nav.setHighlighted(i)}
                  className={optionClass(nav.highlighted === i, isSelected, blocked)}
                >
                  <span className="truncate">
                    {isSelected && (
                      <span aria-hidden="true" className="mr-1.5 text-indigo-600">
                        ✓
                      </span>
                    )}
                    {option.label}
                  </span>
                  {option.description !== undefined && (
                    <span className="shrink-0 text-xs text-slate-500">{option.description}</span>
                  )}
                </li>
              )
            })}

            {canCreate && (
              // role="option", not a button. It inherits arrow navigation,
              // aria-activedescendant and Enter for free, and — unlike
              // SkillAdder's <Button> — adds nothing to the page's button list,
              // which ProfilePage.test.tsx indexes positionally.
              <li
                id={nav.optionId(visible.length)}
                role="option"
                aria-selected={false}
                onClick={() => commit(visible.length)}
                onMouseEnter={() => nav.setHighlighted(visible.length)}
                className={optionClass(nav.highlighted === visible.length, false, false)}
              >
                <span className="truncate">Use “{trimmed}”</span>
              </li>
            )}
          </ul>
        )}

        <span aria-live="polite" className="sr-only">
          {nav.open ? `${count} results` : ''}
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
