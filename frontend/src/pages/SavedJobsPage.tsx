import { SavedJobs } from '@/components/jobs/SavedJobs'

/**
 * Jobs you bookmarked, and jobs you marked applied.
 *
 * A shell. `SavedJobs` is prop-less and owns its own loading, error and empty
 * states, so there is nothing for the page to coordinate.
 *
 * Both lists live here rather than one per route: a row crosses between them
 * the moment "I have applied" is ticked or unticked, and split across two pages
 * that row would appear to vanish with nowhere visible to go.
 */
export function SavedJobsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Saved jobs</h1>
        <p className="mt-1 text-sm text-slate-600">
          Everything you bookmarked while browsing, and the ones you have told us you applied to.
        </p>
      </div>

      <SavedJobs />
    </div>
  )
}
