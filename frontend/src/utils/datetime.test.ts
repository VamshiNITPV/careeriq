import { describe, expect, it } from 'vitest'
import { formatDateTime } from './datetime'

/**
 * The locale is pinned inside the formatter, so the *shape* of the output is
 * deterministic here. The timezone is not — vite.config.ts pins no TZ and
 * src/test/setup.ts stubs neither the clock nor Intl — so the day number and
 * the clock time depend on the machine. Every assertion below holds regardless.
 */

/** "4 Sept 2026, 2:32 pm" — day, month name, year, then a 12-hour time. */
const SHAPE = /^\d{1,2} [A-Z][a-z]+ \d{4}, \d{1,2}:\d{2}\s?[ap]m$/i

describe('formatDateTime', () => {
  it('renders day, month, year and a time', () => {
    expect(formatDateTime('2026-09-04T09:02:00Z')).toMatch(SHAPE)
  })

  it('puts the day before the month', () => {
    // The actual request, and the reason the formatter pins a locale: with the
    // browser default an en-US machine renders "Sep 4, 2026" — month first.
    const result = formatDateTime('2026-09-04T09:02:00Z')
    const month = result.match(/[A-Z][a-z]+/)

    expect(month).not.toBeNull()
    expect(result.indexOf(month![0])).toBeGreaterThan(0)
    // Something numeric precedes the month name.
    expect(result.slice(0, month!.index)).toMatch(/\d/)
  })

  it('names the month rather than numbering it', () => {
    // "9/4/2026" is the format being replaced, and is ambiguous.
    expect(formatDateTime('2026-09-04T09:02:00Z')).not.toMatch(/^\d+\/\d+\/\d+/)
  })

  it('includes a time, which the old format did not', () => {
    expect(formatDateTime('2026-09-04T09:02:00Z')).toMatch(/\d:\d\d/)
  })

  it('renders nothing for a value it cannot parse', () => {
    // "Added Invalid Date" reads as a bug to whoever sees it.
    expect(formatDateTime('')).toBe('')
    expect(formatDateTime('not a date')).toBe('')
  })
})
