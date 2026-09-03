import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { useLocation } from 'react-router-dom'
import { normalizeText } from '@/utils/normalizeText'

/**
 * Shared mechanics for Combobox and MultiCombobox.
 *
 * A plain .ts module, not a component file: it exports a hook, pure functions
 * and class strings, all of which would trip react-refresh/only-export-components
 * if they lived beside a component.
 *
 * The two pickers diverge in real behaviour — what happens after a commit,
 * whether the input clears, whether Backspace removes anything — so they are
 * separate components rather than one with a `multiple` prop. What they share is
 * this: open/close, outside dismissal, highlight arithmetic, the
 * aria-activedescendant id plumbing and scroll-into-view.
 */

export interface ComboboxOption {
  /** The stored value. Unique within a list. */
  value: string
  /** Primary display text, and the main thing searched. */
  label: string
  /** Secondary text shown beside the label. Also searched. */
  description?: string
  /** Extra search terms that are never displayed: alpha-3 codes, former names. */
  keywords?: readonly string[]
}

/* ------------------------------------------------------------------ search */

interface IndexedOption {
  option: ComboboxOption
  value: string
  label: string
  words: string[]
  keywords: string[]
  description: string
}

/**
 * Pre-fold an option list for searching.
 *
 * Call once per list via useMemo keyed on the array identity. The data arrays
 * are module-level constants, so in practice this runs once per mount rather
 * than once per keystroke — normalising 250 labels on every character typed is
 * the easy way to make this feel slow.
 */
export function buildIndex(options: readonly ComboboxOption[]): IndexedOption[] {
  return options.map((option) => {
    const label = normalizeText(option.label)
    return {
      option,
      value: option.value.toLowerCase(),
      label,
      words: label.split(' ').filter(Boolean),
      keywords: (option.keywords ?? []).map(normalizeText),
      description: option.description === undefined ? '' : normalizeText(option.description),
    }
  })
}

/** Lower is better. -1 excludes the option entirely. */
function rank(entry: IndexedOption, query: string): number {
  // An exact code match wins outright: typing "IN" means India, not Indonesia.
  if (entry.value === query) return 0
  if (entry.label.startsWith(query)) return 1
  if (entry.keywords.some((keyword) => keyword.startsWith(query))) return 2
  // Word-start, so "york" finds "New York".
  if (entry.words.some((word) => word.startsWith(query))) return 3
  if (entry.label.includes(query)) return 4
  if (entry.description.includes(query)) return 5
  return -1
}

/**
 * Filter and rank. An empty query returns everything in authored order, which
 * is how the curated weighting in the data files survives to the screen.
 */
export function searchOptions(index: IndexedOption[], rawQuery: string): ComboboxOption[] {
  const query = normalizeText(rawQuery)
  if (query === '') return index.map((entry) => entry.option)

  const scored: { option: ComboboxOption; score: number }[] = []
  for (const entry of index) {
    const score = rank(entry, query)
    if (score >= 0) scored.push({ option: entry.option, score })
  }
  // Array.prototype.sort is stable, so authored order is preserved within each
  // tier — Indian cities stay ahead of US ones for an equally-ranked match.
  scored.sort((a, b) => a.score - b.score)
  return scored.map((item) => item.option)
}

/* ------------------------------------------------------------------ groups */

export interface OptionGroup {
  /** Rendered as the group's accessible name. null means no grouping. */
  label: string | null
  options: ComboboxOption[]
  /** Flat index of this group's first option, for aria-activedescendant. */
  offset: number
}

/**
 * Float a few values to the top under their own heading.
 *
 * Only worth doing while the query is empty: once the user types, relevance is
 * the better order and a pinned block just hides matches.
 */
export function partitionPinned(
  visible: ComboboxOption[],
  pinnedValues: readonly string[] | undefined,
  pinnedLabel: string,
  restLabel: string,
): { flat: ComboboxOption[]; groups: OptionGroup[] } {
  if (pinnedValues === undefined || pinnedValues.length === 0) {
    return { flat: visible, groups: [{ label: null, options: visible, offset: 0 }] }
  }

  const pinnedSet = new Set(pinnedValues)
  const pinned: ComboboxOption[] = []
  const rest: ComboboxOption[] = []
  for (const option of visible) {
    if (pinnedSet.has(option.value)) pinned.push(option)
    else rest.push(option)
  }
  if (pinned.length === 0 || rest.length === 0) {
    return { flat: visible, groups: [{ label: null, options: visible, offset: 0 }] }
  }

  return {
    flat: [...pinned, ...rest],
    groups: [
      { label: pinnedLabel, options: pinned, offset: 0 },
      { label: restLabel, options: rest, offset: pinned.length },
    ],
  }
}

/* ----------------------------------------------------------- navigation */

interface UseComboboxNavArgs {
  /** How many rows are navigable, including any synthetic "use this" row. */
  count: number
  /** Where the highlight lands when the keyboard opens the list. */
  initialHighlight: number
  onCommit: (index: number) => void
  /** Escape, Tab, or a pointer outside. Reset the query here. */
  onDismiss: () => void
}

export function useComboboxNav({
  count,
  initialHighlight,
  onCommit,
  onDismiss,
}: UseComboboxNavArgs) {
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(-1)
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listboxId = useId()
  const location = useLocation()

  const optionId = useCallback((index: number) => `${listboxId}-opt-${index}`, [listboxId])

  const openAt = useCallback((index: number) => {
    setOpen(true)
    setHighlighted(index)
  }, [])

  const dismiss = useCallback(() => {
    setOpen(false)
    setHighlighted(-1)
    onDismiss()
  }, [onDismiss])

  useEffect(() => {
    if (!open || highlighted < 0) return
    // getElementById, not querySelector: React 19's useId produces ids like
    // «r3». Those are legal ids but not legal CSS identifiers, so a selector
    // lookup throws SyntaxError at runtime.
    const element = document.getElementById(optionId(highlighted))
    // Optional call on purpose — jsdom does not implement scrollIntoView and
    // src/test/setup.ts adds no polyfill. Removing the `?.` makes every
    // keyboard test throw. It costs nothing in a browser.
    element?.scrollIntoView?.({ block: 'nearest' })
  }, [open, highlighted, optionId])

  // Close on navigation, so the list is not left hanging over the new page.
  useEffect(() => setOpen(false), [location.pathname])

  useEffect(() => {
    if (!open) return

    const onPointerDown = (event: PointerEvent) => {
      // The input is both the trigger and inside rootRef, so one containment
      // check covers the trigger and the panel. Without it the document handler
      // closes the list in the same gesture that opens it, and the picker looks
      // completely broken. pointerdown rather than click: click fires after
      // mouseup and races the re-render, and pointerdown covers touch.
      if (rootRef.current?.contains(event.target as Node)) return
      setOpen(false)
      setHighlighted(-1)
      onDismiss()
    }

    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open, onDismiss])

  function move(delta: number) {
    if (count === 0) return
    setHighlighted((current) => {
      const next = current < 0 ? (delta > 0 ? 0 : count - 1) : current + delta
      return ((next % count) + count) % count
    })
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        if (open) move(1)
        else openAt(initialHighlight)
        break
      case 'ArrowUp':
        event.preventDefault()
        if (open) move(-1)
        else openAt(count - 1)
        break
      case 'Home':
        if (!open) break
        event.preventDefault()
        setHighlighted(0)
        break
      case 'End':
        if (!open) break
        event.preventDefault()
        setHighlighted(count - 1)
        break
      case 'Enter':
        if (!open) break
        // preventDefault even with nothing highlighted. Both pickers sit inside
        // the profile page's <form>, so without this Enter-to-choose-a-country
        // submits the whole section instead.
        event.preventDefault()
        if (highlighted >= 0) onCommit(highlighted)
        break
      case 'Escape':
        if (!open) break
        event.preventDefault()
        // Stop it reaching an enclosing dialog. Escape dismisses the list and
        // keeps the value — clearing the selection as a side effect surprises
        // people who only meant to close the popover.
        event.stopPropagation()
        dismiss()
        break
      case 'Tab':
        // Not trapped, and deliberately does not commit the highlight: tabbing
        // past a picker and discovering it chose "Turkmenistan" is worse than
        // requiring an explicit Enter.
        if (open) dismiss()
        break
      default:
        break
    }
  }

  return {
    open,
    setOpen,
    highlighted,
    setHighlighted,
    openAt,
    dismiss,
    listboxId,
    optionId,
    rootRef,
    inputRef,
    onKeyDown,
  }
}

/* -------------------------------------------------------------- styling */

/**
 * Full literal class strings throughout. Tailwind v4 scans source text for
 * class names and emits no CSS at all for an interpolated one, so a
 * `bg-${x}-50` highlight would simply not render.
 */
export const listboxClass =
  'absolute top-full left-0 z-30 mt-1 max-h-60 w-full overflow-auto rounded-md ' +
  'border border-slate-200 bg-white py-1 shadow-lg'

export const emptyMessageClass = 'px-3 py-2 text-sm text-slate-500'

export const groupLabelClass =
  'px-3 pt-2 pb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase'

export function optionClass(highlighted: boolean, selected: boolean, disabled: boolean): string {
  const base = 'flex cursor-pointer items-center justify-between gap-3 px-3 py-2 text-sm'
  if (disabled) return `${base} cursor-not-allowed text-slate-400`
  const tone = highlighted ? 'bg-indigo-50 text-indigo-900' : 'text-slate-700'
  return `${base} ${selected ? 'font-medium' : ''} ${tone}`
}
