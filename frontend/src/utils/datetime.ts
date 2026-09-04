/**
 * Render a timestamp as "4 Sept 2026, 2:32 pm" — day, month, year, time.
 *
 * **The locale is pinned, and it has to be.** An options object controls which
 * *parts* a locale renders, never their order. `{ day, month, year }` with the
 * browser default gives "Sep 4, 2026" on an en-US machine — month first. Even a
 * month *name* does not fix the order; it only removes the "04/09 or 09/04?"
 * ambiguity. Day-first is unobtainable without naming a locale.
 *
 * en-IN rather than en-GB because it gives both halves of what was asked for:
 * day-first *and* a 12-hour clock (en-GB renders 14:32). It also matches where
 * this project's users are, which the rest of the codebase already assumes —
 * the curated locations list is India-weighted and the salary parser reads LPA.
 *
 * This is the one deliberate exception to the house style of leaving the locale
 * `undefined` (`formatMonth` in types/career.ts, `formatSalary` in types/job.ts).
 * Those format numbers and month names, where honouring the viewer's convention
 * costs nothing; here the viewer's convention is the thing being overridden.
 *
 * The timezone stays the viewer's own, which is what "when did I upload this"
 * means to them.
 *
 * Only for real timestamps. Month-precision dates — the DATE columns behind
 * work history and education — go through `formatMonth` in types/career.ts,
 * which shows no day and no time because the resume never gave one.
 */
const LOCALE = 'en-IN'

export function formatDateTime(iso: string): string {
  const date = new Date(iso)
  // An empty or malformed value renders as nothing rather than the literal
  // string "Invalid Date", which reads as a bug to whoever sees it.
  if (Number.isNaN(date.getTime())) return ''

  return date.toLocaleString(LOCALE, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}
