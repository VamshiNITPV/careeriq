/**
 * What to call the job page's back link, given where it returns to.
 *
 * The link used to read "Back to jobs" unconditionally, which was wrong
 * wherever the reader had not come from the job list — from Saved jobs it both
 * said and did the wrong thing. Naming the destination means the link can be
 * read before it is clicked, which is the one advantage it has over the
 * browser's own Back button sitting a few pixels away.
 *
 * Pure and separately tested, for the reason `jobListParams` gives: the mapping
 * is the part worth testing and the part least worth rendering a page to test.
 */

/** Pathname prefix → what to call it. Order matters only if prefixes overlap. */
const LABELS: readonly (readonly [string, string])[] = [
  ['/saved-jobs', 'Back to saved jobs'],
  ['/dashboard', 'Back to dashboard'],
]

/** The fallback *and* the answer for `/jobs`, deliberately the same string. */
const DEFAULT_LABEL = 'Back to jobs'

export function backLabelFor(path: string): string {
  // Split on '?' rather than parsing: a query string never changes which page
  // this is, and `/jobs?q=python` must still read "jobs".
  //
  // `split` always yields at least one element, but `noUncheckedIndexedAccess`
  // cannot know that, hence the `?? path`.
  const pathname = path.split('?')[0] ?? path
  return (
    LABELS.find(
      // Whole segments, not a bare `startsWith`: that would read a future
      // `/dashboards-of-my-team` as the dashboard, because the string does
      // begin with it. Matching the exact path or a child of it is what the
      // prefix is actually meant to say.
      ([prefix]) => pathname === prefix || pathname.startsWith(`${prefix}/`),
    )?.[1] ?? DEFAULT_LABEL
  )
}
