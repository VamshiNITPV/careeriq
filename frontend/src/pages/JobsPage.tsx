import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { JobCard } from '@/components/JobCard'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { buttonClass } from '@/components/ui/buttonStyles'
import { Combobox } from '@/components/ui/Combobox'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Spinner } from '@/components/ui/Spinner'
import { ApiError } from '@/services/apiClient'
import { jobService } from '@/services/jobService'
import { EXPERIENCE_YEAR_OPTIONS, POSTED_WITHIN_OPTIONS, type JobSummary } from '@/types/job'
import { EMPLOYMENT_TYPES, WORK_MODES } from '@/types/profile'
import {
  PAGE_SIZE,
  readJobListParams,
  setJobListFilter,
  setJobListOffset,
  type JobFilterKey,
} from '@/utils/jobListParams'

/**
 * Browse the job corpus.
 *
 * Ranking is Phase 6 — this lists newest-first with filters. Deliberately not
 * dressed up as recommendations: showing an unranked list under a heading that
 * implies personalisation would be a claim the system cannot yet support.
 */

const SEARCH_DEBOUNCE_MS = 300

export function JobsPage() {
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)

  const [searchParams, setSearchParams] = useSearchParams()

  // Destructured to primitives on purpose. The object this returns has a new
  // identity every render, and putting it in `load`'s dependency array below
  // would turn `useEffect(load, [load])` into an unbounded refetch loop — one
  // that would also keep overwriting the in-place row swap that
  // `onApplicationChange` performs.
  const { q, workMode, employmentType, yearsValue, postedWithin, offset } =
    readJobListParams(searchParams)

  // What the input shows, versus what the URL holds. Separated so typing stays
  // responsive while requests lag behind it. Seeded from the URL, so arriving
  // at /jobs?q=python shows "python" in the box rather than an empty field
  // sitting over a filtered list.
  const [searchText, setSearchText] = useState(q)
  const [lastQ, setLastQ] = useState(q)

  const requestId = useRef(0)

  // Adjusting state during render, which is deliberate and not something to be
  // "tidied" into an effect: Back, or a pasted link, changes `q` underneath us
  // and the box has to follow in the same pass. An effect would run a render
  // late and race the debounce below.
  if (q !== lastQ) {
    setLastQ(q)
    // Guarded against our own debounced write, which would otherwise snap the
    // caret: typing "python " settles `q` to "python", and rewriting the box
    // would eat the trailing space the user is still typing past.
    if (q !== searchText.trim()) setSearchText(q)
  }

  useEffect(() => {
    const next = searchText.trim()
    // The loop-breaker, and the mount guard. React Router does not diff URLs,
    // so without this every arrival on the page fires a navigation to the URL
    // it is already on.
    if (next === q) return
    const timer = window.setTimeout(() => {
      setSearchParams((previous) => setJobListFilter(previous, 'q', next), { replace: true })
    }, SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [searchText, q, setSearchParams])

  /**
   * Write one filter. `setJobListFilter` drops the page along with it.
   *
   * `replace`, not push: even debounced, a typed search is several history
   * entries, and ten searches would mean a Back button that no longer leaves
   * /jobs. A push would also only half-fix the bug this exists for — Back from
   * a job would land on the second-to-last filter state.
   */
  const setFilter = useCallback(
    (key: JobFilterKey, value: string) =>
      setSearchParams((previous) => setJobListFilter(previous, key, value), { replace: true }),
    [setSearchParams],
  )

  // Pushed, unlike the filters: a page is a real position in a list, it is one
  // deliberate click, and it cannot flood history the way keystrokes can.
  const goToOffset = useCallback(
    (next: number) => setSearchParams((previous) => setJobListOffset(previous, next)),
    [setSearchParams],
  )

  const load = useCallback(() => {
    const id = ++requestId.current
    setLoadState('loading')
    setError(null)

    jobService
      .list({
        ...(q ? { q } : {}),
        ...(workMode ? { work_mode: workMode } : {}),
        ...(employmentType ? { employment_type: employmentType } : {}),
        // Compared against '' rather than tested for truthiness: "0+ years" is
        // a real filter, and Number('0') is falsy.
        ...(yearsValue !== '' ? { years_experience: Number(yearsValue) } : {}),
        ...(postedWithin !== '' ? { posted_within_days: Number(postedWithin) } : {}),
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
  }, [q, workMode, employmentType, yearsValue, postedWithin, offset])

  useEffect(load, [load])

  // Same reason as the request itself. Miss it here and "0+ years" renders
  // "No jobs yet." with an Add-a-job button while a filter is active.
  const hasFilters =
    q !== '' ||
    workMode !== '' ||
    employmentType !== '' ||
    yearsValue !== '' ||
    postedWithin !== ''

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
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
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
            onChange={(e) => setFilter('work_mode', e.target.value)}
          />
          <Select
            label="Employment type"
            placeholder="Any"
            options={EMPLOYMENT_TYPES}
            value={employmentType}
            onChange={(e) => setFilter('employment_type', e.target.value)}
          />
          {/*
            A Combobox rather than a native Select: eleven options is short
            enough for either, but this one supports typing to filter as well as
            arrowing. It commits on selection, so unlike the free-text box it
            replaced there is nothing to debounce and no invalid value to guard
            against — only list options can be chosen. Clearing back to "Any" is
            the × button.
          */}
          <Combobox
            label="Your experience"
            options={EXPERIENCE_YEAR_OPTIONS}
            value={yearsValue}
            onChange={(value) => setFilter('years_experience', value)}
            placeholder="Any"
            hint="Shows jobs whose stated range covers you. Postings that don't say are still shown."
          />
          {/*
            A native Select, unlike the years Combobox beside it: four options
            is too few to be worth typing through, and the Combobox's filtering
            earns nothing here.
          */}
          <Select
            label="Posted within"
            placeholder="Any time"
            options={POSTED_WITHIN_OPTIONS}
            value={postedWithin}
            onChange={(e) => setFilter('posted_within_days', e.target.value)}
            hint="Postings with no stated date are still shown."
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
      ) : jobs.length === 0 && offset > 0 ? (
        /*
          An empty page that is not an empty list. Only reachable by editing the
          URL — the pager disables Next at the end — but reachable, and "No jobs
          match those filters" would be a lie that sends the user off widening a
          search that is fine.

          A button rather than an effect that resets the offset after an empty
          load: that would be a write derived from a response, which is the loop
          shape this page's URL state deliberately avoids, and it would teleport
          the user instead of telling them what happened.
        */
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center">
          <p className="text-sm font-medium text-slate-900">
            That page is past the end of these results.
          </p>
          <p className="mt-1 text-sm text-slate-600">
            There {total === 1 ? 'is 1 job' : `are ${total} jobs`} to show.
          </p>
          <Button
            variant="secondary"
            size="sm"
            className="mt-4"
            onClick={() => goToOffset(0)}
          >
            Back to the first page
          </Button>
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
              <JobCard
                key={job.id}
                job={job}
                // Swap the one row rather than reloading the page. A refetch
                // would reset scroll and re-run the filters to produce the
                // same list, and would race the requestId guard above.
                onApplicationChange={(application) =>
                  setJobs((previous) =>
                    previous.map((row) => (row.id === job.id ? { ...row, application } : row)),
                  )
                }
              />
            ))}
          </ul>

          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between border-t border-slate-200 pt-4">
              <Button
                variant="secondary"
                size="sm"
                disabled={offset === 0}
                onClick={() => goToOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => goToOffset(offset + PAGE_SIZE)}
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
