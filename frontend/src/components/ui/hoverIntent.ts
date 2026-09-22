import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Opening a menu because a pointer rested on it, and closing it when that
 * pointer leaves.
 *
 * A plain `.ts` module, not a component file, for the reason `popoverDismiss.ts`
 * states: a hook exported beside a component trips
 * `react-refresh/only-export-components`. Shared for the reason that file gives
 * for its own existence — this is wanted in two places (the account menu and the
 * header's disclosure), and the second copy is where drift starts.
 *
 * ## Only where a pointer can actually hover
 *
 * Gated on `(hover: hover) and (pointer: fine)`. Without the gate touch is not
 * merely unimproved, it is **broken**: a tap fires `pointerenter` and then
 * `click`, so the enter opens the menu and the click immediately toggles it
 * shut. The menu would need two taps and look defective — and the people
 * affected are exactly those who cannot hover to work around it.
 *
 * ## Both delays are load-bearing
 *
 * **Open (120ms)** so a cursor crossing the header on its way somewhere else
 * does not fling menus open behind it. Hover-opened menus with no intent delay
 * are a well-known irritation rather than a feature.
 *
 * **Close (200ms)** because the trigger and its panel are not touching —
 * `DropdownMenu` puts an 8px gap between them (`mt-2`). During that crossing the
 * pointer is over neither, so an instant close would shut the menu while the
 * user is reaching into it. The delay also satisfies the "hoverable" half of
 * WCAG 1.4.13: content revealed on hover has to survive the pointer moving onto
 * it.
 *
 * ## It never returns focus
 *
 * Deliberately no focus handling here, in contrast to `DropdownMenu`'s Escape
 * path which moves focus back to the trigger. That is right for a keyboard
 * dismissal and wrong for this one: the pointer is somewhere else entirely, and
 * yanking the focus ring back to a menu the user has just walked away from
 * would move it under their feet.
 */

interface UseHoverIntentArgs {
  onOpen: () => void
  onClose: () => void
  openDelay?: number
  closeDelay?: number
}

interface HoverIntent {
  /** Whether this device can hover at all. False on touch, and in jsdom. */
  enabled: boolean
  onPointerEnter: () => void
  onPointerLeave: () => void
}

const FINE_POINTER = '(hover: hover) and (pointer: fine)'

export function useHoverIntent({
  onOpen,
  onClose,
  openDelay = 120,
  closeDelay = 200,
}: UseHoverIntentArgs): HoverIntent {
  const [enabled, setEnabled] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Callbacks in a ref so the effects below do not depend on them. Callers pass
  // inline arrows, and listing those would re-run this on every render — the
  // same trap `popoverDismiss.ts` documents.
  const handlers = useRef({ onOpen, onClose })
  useEffect(() => {
    handlers.current = { onOpen, onClose }
  })

  useEffect(() => {
    // Read in an effect, not during render: `matchMedia` is a browser API, and
    // touching it while rendering would break any future server render. It is
    // also absent in jsdom, which the test setup polyfills.
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia(FINE_POINTER)
    setEnabled(query.matches)

    // Listened to rather than read once: plugging in a mouse, or docking a
    // tablet to a keyboard, changes the answer mid-session.
    const onChange = (event: MediaQueryListEvent) => setEnabled(event.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  const clear = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current)
    timer.current = null
  }, [])

  // A pending open or close must not fire after unmount — it would call
  // setState on a gone component, and in a test it outlives the assertion.
  useEffect(() => clear, [clear])

  const onPointerEnter = useCallback(() => {
    if (!enabled) return
    // Cancels a pending *close* as well as a pending open, which is what makes
    // the gap between trigger and panel survivable.
    clear()
    timer.current = setTimeout(() => handlers.current.onOpen(), openDelay)
  }, [enabled, clear, openDelay])

  const onPointerLeave = useCallback(() => {
    if (!enabled) return
    clear()
    timer.current = setTimeout(() => handlers.current.onClose(), closeDelay)
  }, [enabled, clear, closeDelay])

  return { enabled, onPointerEnter, onPointerLeave }
}
