import { ApplicationBoard } from '@/components/applications/ApplicationBoard'

/**
 * Where an application is, and moving it on (US-7.1).
 *
 * This replaced `/saved-jobs`, which answered "what have I bookmarked or
 * applied to" as a flat pair of lists. That was a second view of these same
 * rows, and two views of one list can disagree; the funnel answers "where is
 * each one", which is the more useful question and contains the other.
 *
 * A shell. `ApplicationBoard` is prop-less and owns its own loading, error and
 * empty states, so there is nothing for the page to coordinate.
 */
export function ApplicationsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Applications</h1>
        <p className="mt-1 text-sm text-slate-600">
          Every stage is something you told us about — nothing here moves on its own. Changes are
          recorded with their date, so you can see how long each one took.
        </p>
      </div>

      <ApplicationBoard />
    </div>
  )
}
