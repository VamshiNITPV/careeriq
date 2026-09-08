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

afterEach(() => {
  // Unmount rendered trees. Without this, components from an earlier test stay
  // in the document and queries match the wrong element — producing failures
  // that depend on test execution order.
  cleanup()
  localStorage.clear()
  vi.restoreAllMocks()
})
