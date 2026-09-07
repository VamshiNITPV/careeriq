import { describe, expect, it } from 'vitest'
import { formatDateTime, formatPostedAge } from './datetime'

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

describe('formatPostedAge', () => {
  // A fixed "now" so these do not start failing at midnight or next month.
  const now = new Date(2026, 8, 7, 10, 0, 0) // 7 September 2026, local time

  const at = (year: number, month: number, day: number) =>
    new Date(year, month, day, 9, 0, 0).toISOString()

  it('says plainly when no date was given', () => {
    // Over half the corpus has no date. Rendering nothing would read as
    // "posted recently" — a claim the employer never made.
    expect(formatPostedAge(null, now)).toBe('Posting date not given')
  })

  it('says the same for a value it cannot parse', () => {
    expect(formatPostedAge('not a date', now)).toBe('Posting date not given')
  })

  it('counts today, yesterday and days', () => {
    expect(formatPostedAge(at(2026, 8, 7), now)).toBe('Posted today')
    expect(formatPostedAge(at(2026, 8, 6), now)).toBe('Posted yesterday')
    expect(formatPostedAge(at(2026, 8, 4), now)).toBe('Posted 3 days ago')
  })

  it('counts whole calendar days, not elapsed hours', () => {
    // Posted at 11pm yesterday, read at 10am today. An hours-based count would
    // call this 11 hours — under a day — and say "today".
    const lateYesterday = new Date(2026, 8, 6, 23, 0, 0).toISOString()

    expect(formatPostedAge(lateYesterday, now)).toBe('Posted yesterday')
  })

  it('switches to months once days stop being readable', () => {
    expect(formatPostedAge(at(2026, 7, 10), now)).toBe('Posted 28 days ago')
    expect(formatPostedAge(at(2026, 7, 5), now)).toBe('Posted about a month ago')
    expect(formatPostedAge(at(2026, 5, 7), now)).toBe('Posted about 3 months ago')
  })

  it('treats a future date as today', () => {
    // Clock skew between the provider, the server and the viewer is real, and
    // "Posted in 2 days" reads as a bug.
    expect(formatPostedAge(at(2026, 8, 9), now)).toBe('Posted today')
  })
})
