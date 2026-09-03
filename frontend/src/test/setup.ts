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

afterEach(() => {
  // Unmount rendered trees. Without this, components from an earlier test stay
  // in the document and queries match the wrong element — producing failures
  // that depend on test execution order.
  cleanup()
  localStorage.clear()
  vi.restoreAllMocks()
})
