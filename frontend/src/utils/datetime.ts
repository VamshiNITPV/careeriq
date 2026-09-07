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

/**
 * How long ago a posting went up — "Posted 3 days ago", or that nobody said.
 *
 * **Why an explicit "not given" rather than nothing.** Measured on the corpus
 * on 2026-09-07: 97 of 183 active postings carry no date, and 90 of those came
 * from the provider rather than from hand entry. Rendering silence for over
 * half the list would read as "recently posted" by default, which is a claim
 * nobody made (ADR-012). The gap is stated instead.
 *
 * Days, not hours: the corpus is refreshed on a daily schedule and the provider
 * reports whole days, so "4 hours ago" would be precision the data has not got.
 *
 * A future date renders as "today". Clock skew between the provider, the server
 * and the viewer's machine is real, and "Posted in 2 days" reads as a bug.
 */
export function formatPostedAge(iso: string | null, now: Date = new Date()): string {
  if (iso === null) return 'Posting date not given'

  const posted = new Date(iso)
  if (Number.isNaN(posted.getTime())) return 'Posting date not given'

  // Whole days between calendar dates, not between instants: a job posted at
  // 11pm yesterday is "yesterday" at 1am, not "1 day ago" for one hour and
  // "2 days ago" after. Both sides are floored to local midnight first.
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const days = Math.floor((startOfDay(now) - startOfDay(posted)) / 86_400_000)

  if (days <= 0) return 'Posted today'
  if (days === 1) return 'Posted yesterday'
  if (days < 30) return `Posted ${days} days ago`

  const months = Math.floor(days / 30)
  return months === 1 ? 'Posted about a month ago' : `Posted about ${months} months ago`
}
