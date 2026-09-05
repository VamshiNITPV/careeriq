import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from 'react'
import { usePopoverDismiss } from '@/components/ui/popoverDismiss'
import { cn } from '@/utils/cn'

/**
 * An accessible dropdown menu.
 *
 * A shared component rather than something inlined where it is used: the
 * behaviour below is roughly ninety lines of easy-to-get-wrong detail, and the
 * one existing precedent in this codebase (the mobile nav disclosure in
 * AppLayout) is missing click-outside dismissal and focus return. Writing it
 * once means the next menu inherits the correct version instead of a worse
 * reimplementation.
 *
 * Children provide the items. Anything with `role="menuitem"` participates in
 * keyboard navigation, which is why they are queried from the DOM rather than
 * passed as an array — it keeps the API open to links, buttons and separators.
 */

interface DropdownMenuProps {
  /** Rendered inside the trigger button. */
  trigger: ReactNode
  children: ReactNode
  align?: 'left' | 'right'
  /** Accessible name for the trigger. */
  label: string
  triggerClassName?: string
  className?: string
}

export function DropdownMenu({
  trigger,
  children,
  align = 'right',
  label,
  triggerClassName,
  className,
}: DropdownMenuProps) {
  const [open, setOpen] = useState(false)
  // Which item to focus once the panel has actually rendered.
  const [pendingFocus, setPendingFocus] = useState<number | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const panelId = useId()
  const triggerId = useId()

  // One ref on the wrapper covers the trigger and the panel together. The
  // trigger must be inside it: otherwise the document handler closes the menu
  // in the same gesture that the trigger's onClick opens it, and the menu
  // appears completely broken.
  const rootRef = usePopoverDismiss<HTMLDivElement>({
    open,
    onOutsidePointer: () => setOpen(false),
    onRouteChange: () => setOpen(false),
  })

  const items = useCallback(
    () => Array.from(panelRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []),
    [],
  )

  const focusItem = useCallback(
    (index: number) => {
      const all = items()
      if (all.length === 0) return
      // Wraparound: from the last item, down goes to the first.
      const target = ((index % all.length) + all.length) % all.length
      all[target]?.focus()
    },
    [items],
  )

  const close = useCallback((returnFocus: boolean) => {
    setOpen(false)
    if (returnFocus) triggerRef.current?.focus()
  }, [])

  // Focus is applied in an effect rather than immediately after setOpen, and
  // rather than inside requestAnimationFrame: the panel does not exist in the
  // DOM until React has committed the render, so focusing any earlier is a
  // no-op. An effect is the first point where the items are guaranteed to be
  // mounted, and unlike rAF it is deterministic under test.
  useEffect(() => {
    if (!open || pendingFocus === null) return
    focusItem(pendingFocus)
    setPendingFocus(null)
  }, [open, pendingFocus, focusItem])

  function onTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      setOpen(true)
      setPendingFocus(0)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setOpen(true)
      // -1 wraps to the last item.
      setPendingFocus(-1)
    }
  }

  function onPanelKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const all = items()
    const current = all.indexOf(document.activeElement as HTMLElement)

    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        focusItem(current + 1)
        break
      case 'ArrowUp':
        event.preventDefault()
        focusItem(current - 1)
        break
      case 'Home':
        event.preventDefault()
        focusItem(0)
        break
      case 'End':
        event.preventDefault()
        focusItem(-1)
        break
      case 'Escape':
        event.preventDefault()
        close(true)
        break
      case 'Tab':
        // Deliberately NOT trapped. A menu button is not a modal dialog, and
        // trapping Tab here is the most common hand-rolled-menu bug — it leaves
        // keyboard users unable to move past the menu at all.
        setOpen(false)
        break
      default:
        break
    }
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={label}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={onTriggerKeyDown}
        className={cn(
          'rounded-full focus-visible:outline-2 focus-visible:outline-offset-2',
          'focus-visible:outline-indigo-600',
          triggerClassName,
        )}
      >
        {trigger}
      </button>

      {open && (
        <div
          ref={panelRef}
          id={panelId}
          role="menu"
          aria-labelledby={triggerId}
          onKeyDown={onPanelKeyDown}
          // Selecting an item closes the menu and hands focus back, so keyboard
          // users are not dropped at the top of the document.
          onClick={() => close(true)}
          className={cn(
            'absolute top-full z-30 mt-2 w-60 max-w-[calc(100vw-2rem)] overflow-hidden',
            'rounded-lg border border-slate-200 bg-white py-1 shadow-lg',
            align === 'right' ? 'right-0' : 'left-0',
            className,
          )}
        >
          {children}
        </div>
      )}
    </div>
  )
}

/** Shared styling for anything acting as a menu item. */
export const menuItemClass =
  'block w-full px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-100 ' +
  'focus:bg-slate-100 focus:outline-none'
