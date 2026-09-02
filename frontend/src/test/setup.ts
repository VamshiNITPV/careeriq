import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  // Unmount rendered trees. Without this, components from an earlier test stay
  // in the document and queries match the wrong element — producing failures
  // that depend on test execution order.
  cleanup()
  localStorage.clear()
  vi.restoreAllMocks()
})
