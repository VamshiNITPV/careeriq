import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { JobCard } from '@/components/JobCard'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { buttonClass } from '@/components/ui/buttonStyles'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Spinner } from '@/components/ui/Spinner'
import { ApiError } from '@/services/apiClient'
import { jobService } from '@/services/jobService'
import { type JobSummary } from '@/types/job'
import {
  EMPLOYMENT_TYPES,
  WORK_MODES,
  type EmploymentType,
  type WorkMode,
} from '@/types/profile'

/**
 * Browse the job corpus.
 *
 * Ranking is Phase 6 — this lists newest-first with filters. Deliberately not
 * dressed up as recommendations: showing an unranked list under a heading that
 * implies personalisation would be a claim the system cannot yet support.
 */

const PAGE_SIZE = 20
/** Renamed from SEARCH_DEBOUNCE_MS — two inputs use it now. */
const FILTER_DEBOUNCE_MS = 300
/** Mirrors Query(le=60) in backend/app/api/v1/jobs.py. */
const MAX_YEARS = 60
/** One or two digits, optionally one decimal — the shape Numeric(4,1) accepts. */
const YEARS_PATTERN = /^\d{1,2}(\.\d)?$/

/**
 * A usable years filter, or nothing.
 *
 * The `^\d` anchor is what actually rejects a negative: `min={0}` on a number
 * input only sets validity.rangeUnderflow and constrains the steppers, it does
 * not stop "-3" being typed.
 */
function parseYears(text: string): number | null {
  const trimmed = text.trim()
  if (!YEARS_PATTERN.test(trimmed)) return null
  const value = Number(trimmed)
  return value <= MAX_YEARS ? value : null
}

export function JobsPage() {
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)

  // What the input shows, versus what has been sent. Separated so typing stays
  // responsive while requests lag behind it.
  const [searchText, setSearchText] = useState('')
  const [query, setQuery] = useState('')
  const [workMode, setWorkMode] = useState<WorkMode | ''>('')
  const [employmentType, setEmploymentType] = useState<EmploymentType | ''>('')
  // Same split as searchText/query: what the box shows, versus what has been
  // committed and sent.
  const [yearsText, setYearsText] = useState('')
  const [years, setYears] = useState<number | null>(null)

  const requestId = useRef(0)

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(searchText.trim()), FILTER_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [searchText])

  /**
   * Debounced for a stronger reason than the search box.
   *
   * A partial search term is a narrower query returning a subset. A partial
   * years value is a *valid, different* filter — typing "12" would fire
   * years_experience: 1 first, flashing a genuinely different result set before
   * replacing it.
   */
  useEffect(() => {
    const timer = window.setTimeout(() => setYears(parseYears(yearsText)), FILTER_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [yearsText])

  // Any filter change puts the user back on page one. Without this, narrowing
  // a search while on page three shows an empty list that looks like no
  // results. Keyed on the committed values, never the raw text — otherwise
  // every keystroke resets the page and fires a request.
  useEffect(() => setOffset(0), [query, workMode, employmentType, years])

  const load = useCallback(() => {
    const id = ++requestId.current
    setLoadState('loading')
    setError(null)

    jobService
      .list({
        ...(query ? { q: query } : {}),
        ...(workMode ? { work_mode: workMode } : {}),
        ...(employmentType ? { employment_type: employmentType } : {}),
        // `years !== null`, not a falsy check: 0 is a real filter, and the
        // truthiness pattern used above would silently drop it.
        ...(years !== null ? { years_experience: years } : {}),
        limit: PAGE_SIZE,
        offset,
      })
      .then(
        (response) => {
          // A slower earlier request must not overwrite a faster later one.
          if (id !== requestId.current) return
          setJobs(response.items)
          setTotal(response.total)
          setLoadState('ready')
        },
        (caught: unknown) => {
          if (id !== requestId.current) return
          setError(
            caught instanceof ApiError ? caught.message : 'Could not load jobs. Please try again.',
          )
          setLoadState('error')
        },
      )
  }, [query, workMode, employmentType, years, offset])

  useEffect(load, [load])

  // Same reason as the request itself: 0 is a filter. Miss it here and "0
  // years" renders "No jobs yet." with an Add-a-job button while a filter is
  // active.
  const hasFilters = query !== '' || workMode !== '' || employmentType !== '' || years !== null

  // Derived, not state, so the message appears on the keystroke while the
  // request stays debounced.
  const yearsError =
    yearsText.trim() !== '' && parseYears(yearsText) === null
      ? `Enter a number of years between 0 and ${MAX_YEARS}.`
      : undefined
  const showing = jobs.length > 0 ? `${offset + 1}–${offset + jobs.length} of ${total}` : null

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Jobs</h1>
          <p className="mt-1 text-sm text-slate-600">
            Every posting anyone has added. Paste one and we&apos;ll pull out its requirements.
          </p>
        </div>
        <Link to="/jobs/new" className={buttonClass()}>
          Add a job
        </Link>
      </div>

      <div className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Input
            label="Search"
            type="search"
            placeholder="Title or description"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
          <Select
            label="Work mode"
            placeholder="Any"
            options={WORK_MODES}
            value={workMode}
            onChange={(e) => setWorkMode(e.target.value as WorkMode | '')}
          />
          <Select
            label="Employment type"
            placeholder="Any"
            options={EMPLOYMENT_TYPES}
            value={employmentType}
            onChange={(e) => setEmploymentType(e.target.value as EmploymentType | '')}
          />
          <Input
            label="Your experience"
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_YEARS}
            step={1}
            placeholder="Any"
            value={yearsText}
            onChange={(e) => setYearsText(e.target.value)}
            // A focused number input increments on the scroll wheel, and every
            // increment would fire a request 300ms later — on a page whose whole
            // purpose is scrolling. Blurring on wheel is the standard fix.
            onWheel={(e) => e.currentTarget.blur()}
            hint="Years. Shows jobs whose stated range covers your number; postings that don't say are still shown."
            error={yearsError}
          />
        </div>
      </div>

      {error !== null && (
        <Alert tone="error" title="We couldn't load jobs">
          {error}
        </Alert>
      )}

      {loadState === 'error' ? (
        <Button variant="secondary" size="sm" onClick={load}>
          Try again
        </Button>
      ) : loadState === 'loading' ? (
        <div className="flex justify-center py-12">
          <Spinner className="size-6 text-indigo-600" label="Loading jobs" />
        </div>
      ) : jobs.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center">
          <p className="text-sm font-medium text-slate-900">
            {hasFilters ? 'No jobs match those filters.' : 'No jobs yet.'}
          </p>
          <p className="mt-1 text-sm text-slate-600">
            {hasFilters
              ? 'Try widening the search.'
              : 'Paste a posting you are interested in to get started.'}
          </p>
          {!hasFilters && (
            <Link to="/jobs/new" className={buttonClass({ className: 'mt-4' })}>
              Add a job
            </Link>
          )}
        </div>
      ) : (
        <>
          <p className="text-sm text-slate-500" role="status">
            Showing {showing}
          </p>
          <ul className="space-y-3">
            {jobs.map((job) => (
              <JobCard key={job.id} job={job} />
            ))}
          </ul>

          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between border-t border-slate-200 pt-4">
              <Button
                variant="secondary"
                size="sm"
                disabled={offset === 0}
                onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset((current) => current + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
