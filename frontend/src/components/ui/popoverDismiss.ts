import { useEffect, useRef, type RefObject } from 'react'
import { useLocation } from 'react-router-dom'

/**
 * The two ways a popover closes without anyone choosing anything: a pointer
 * lands outside it, or the route changes underneath it.
 *
 * A plain .ts module, not a component file, for the reason comboboxCore states:
 * a hook exported beside a component trips react-refresh/only-export-components.
 *
 * Extracted because this was written twice already — once in comboboxCore and
 * once in DropdownMenu — with the same rationale comment copied between them.
 * A third copy in MonthPicker is where the drift starts.
 *
 * Consumers must render inside a Router, since this reads the location.
 */

interface UsePopoverDismissArgs {
  open: boolean
  /**
   * A pointer went down outside the returned ref. Kept separate from the route
   * case because the callers genuinely differ: a combobox also resets its typed
   * query here, but on navigation it only needs to close.
   */
  onOutsidePointer: () => void
  /** The route changed. Close, so the panel is not left over the new page. */
  onRouteChange: () => void
}

/**
 * Returns the ref to put on the element that encloses **both** the trigger and
 * the panel. One containment check then covers both, which is what stops the
 * document handler closing the popover in the same gesture that opened it.
 */
export function usePopoverDismiss<T extends HTMLElement = HTMLDivElement>({
  open,
  onOutsidePointer,
  onRouteChange,
}: UsePopoverDismissArgs): RefObject<T | null> {
  const rootRef = useRef<T>(null)
  const location = useLocation()

  // The callbacks are held in a ref so the effects below depend only on `open`
  // and the pathname. Callers pass inline arrows, and listing those in a
  // dependency array would re-run the route effect on every render — closing
  // the popover in the same commit that opened it.
  //
  // Declared before the effects that read it: effects run in source order, so
  // this is always refreshed first.
  const handlers = useRef({ onOutsidePointer, onRouteChange })
  useEffect(() => {
    handlers.current = { onOutsidePointer, onRouteChange }
  })

  useEffect(() => {
    handlers.current.onRouteChange()
  }, [location.pathname])

  useEffect(() => {
    if (!open) return

    const onPointerDown = (event: PointerEvent) => {
      if (rootRef.current?.contains(event.target as Node)) return
      handlers.current.onOutsidePointer()
    }

    // pointerdown, not click: click fires after mouseup and races with the
    // re-render, and pointerdown covers touch as well.
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  return rootRef
}
