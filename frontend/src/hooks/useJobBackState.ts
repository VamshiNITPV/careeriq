import { useLocation } from 'react-router-dom'
import type { JobDetailLocationState } from '@/types/job'

/**
 * Where a link into a job page should come back to: this page, as it is now.
 *
 * Every `<Link>` to `/jobs/:id` needs this, because `JobDetailPage` falls back
 * to `/jobs` when the state is absent — silently, and looking plausible, since
 * `/jobs` is a real page a reader might have come from.
 *
 * **Shared because deriving it inline did not scale.** It started as two lines
 * inside `JobCard`, with a comment arguing that deriving it there beat passing
 * it as a prop, since "a prop is one a new call site can forget". That was
 * right about the risk and wrong about the remedy: it protected `JobCard` and
 * nothing else, and the three links added later — the saved-jobs row, and "see
 * why" on the dashboard and in the job list — each forgot it. The job list one
 * was the worst, because the card's own title kept the reader's filters while
 * the link directly beneath it threw them away.
 *
 * `search` is included, not just the path. `/jobs?q=python&offset=20` is a
 * different list from `/jobs`, and returning to the unfiltered first page is
 * the bug this whole mechanism exists to prevent.
 *
 * The value is not trusted on the way back in — `JobDetailPage` re-validates it
 * as an in-app path, because history state is writable by any script on the
 * page.
 */
export function useJobBackState(): JobDetailLocationState {
  const location = useLocation()
  // `satisfies` earns its keep: React Router types link state as `any`, so this
  // is the only thing checking the shape at any of the call sites.
  return { backTo: `${location.pathname}${location.search}` } satisfies JobDetailLocationState
}
