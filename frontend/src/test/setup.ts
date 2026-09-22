import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

/**
 * jsdom does not implement the modal dialog API.
 *
 * ConfirmDialog calls showModal() inside an effect, so without this the
 * exception takes the whole render down — not a degraded test, a failed one.
 * Feature-guarded so it disappears the day jsdom ships its own.
 *
 * This gives no top layer and no inertness, so a test cannot prove anything
 * about what is or is not reachable behind the backdrop. It only makes the
 * dialog mountable.
 */
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true
  }
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.open = false
    // ConfirmDialog syncs its React state from this event. Without dispatching
    // it, cancelling leaves the caller's state set and the test wedges.
    this.dispatchEvent(new Event('close'))
  }
}

/**
 * jsdom implements Blob but not the object-URL registry.
 *
 * Both functions are simply absent, so anything that renders a fetched file
 * throws on mount. The counter suffix matters: a test proving the *first* URL
 * was revoked has to be able to tell two of them apart.
 *
 * Feature-guarded so it disappears the day jsdom ships its own, and defined
 * here rather than per-test because `vi.spyOn` cannot stub a missing property.
 */
if (typeof URL.createObjectURL !== 'function') {
  let created = 0
  URL.createObjectURL = () => `blob:mock/${++created}`
  URL.revokeObjectURL = () => {}
}

/**
 * jsdom does not implement `matchMedia`.
 *
 * `useHoverIntent` calls it on mount, so without this every test rendering a
 * menu — which is most of them — dies on a missing function rather than on
 * anything it was written to check.
 *
 * **Defaults to `matches: false`, meaning "this device cannot hover".** That is
 * the honest default for a headless DOM with no pointer, and it makes the safe
 * case the one you get for free: hover does nothing unless a test says
 * otherwise. Tests that want hover stub this explicitly, which forces each of
 * them to state the environment it is assuming instead of inheriting it.
 *
 * Feature-guarded so it disappears the day jsdom ships its own. It provides no
 * real media evaluation — the query string is ignored — so nothing here can
 * prove a breakpoint works. Only that the call does not throw.
 */
if (typeof window.matchMedia !== 'function') {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
      // Deprecated, and still what some libraries reach for first.
      addListener: () => {},
      removeListener: () => {},
    }) as MediaQueryList
}

afterEach(() => {
  // Unmount rendered trees. Without this, components from an earlier test stay
  // in the document and queries match the wrong element — producing failures
  // that depend on test execution order.
  cleanup()
  localStorage.clear()
  vi.restoreAllMocks()
})
