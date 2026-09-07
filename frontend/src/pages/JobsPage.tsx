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
import { cn } from '@/utils/cn'
import {
  countActiveJobFilters,
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

/**
 * The funnel on the Filters button.
 *
 * Local and unexported, following MenuIcon in AppLayout and BookmarkIcon in
 * JobSaveControls: there is no icon library here, and a component exported from
 * a .tsx page file trips react-refresh/only-export-components.
 */
function FilterIcon() {
  return (
    <svg
      className="size-4"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4 5h16l-6 7v5l-4 2v-7L4 5Z" />
    </svg>
  )
}

export function JobsPage() {
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)

  const [searchParams, setSearchParams] = useSearchParams()

  // Destructured to primitives on purpose. `params` and the object it came from
  // both have a new identity every render, so neither may enter `load`'s
  // dependency array below — that would turn `useEffect(load, [load])` into an
  // unbounded refetch loop, one that would also keep overwriting the in-place
  // row swap `onApplicationChange` performs. `load` depends on the six
  // primitives and nothing else; `params` exists only to be counted.
  const params = readJobListParams(searchParams)
  const { q, workMode, employmentType, yearsValue, postedWithin, offset } = params

  // What the input shows, versus what the URL holds. Separated so typing stays
  // responsive while requests lag behind it. Seeded from the URL, so arriving
  // at /jobs?q=python shows "python" in the box rather than an empty field
  // sitting over a filtered list.
  const [searchText, setSearchText] = useState(q)
  const [lastQ, setLastQ] = useState(q)

  const requestId = useRef(0)

  // Below lg the four dropdowns collapse behind a button, so the results are
  // not pushed off the first screen by three rows of filters.
  //
  // Always closed on arrival, never seeded from the active filters: someone
  // following a shared /jobs?work_mode=REMOTE link came for the results, and
  // opening the panel for them pushes those results down — the very thing this
  // exists to prevent. The count on the button is what tells them instead.
  const [filtersOpen, setFiltersOpen] = useState(false)
  const filtersTrigger = useRef<HTMLButtonElement>(null)

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
  const activeFilterCount = countActiveJobFilters(params)
  const hasFilters = activeFilterCount > 0

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

      <div
        className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200"
        /*
          Escape as a React handler on the card, not a document listener like
          AppLayout's nav. comboboxCore's Escape case calls stopPropagation to
          stop it reaching an enclosing dialog, and a handler on a React
          ancestor is the one place that is definitively honoured — so one
          Escape closes the experience list and keeps its value, and a second
          closes this panel. It also scopes Escape correctly: pressing it while
          reading the job list should not collapse the filters.
        */
        onKeyDown={(event) => {
          if (event.key !== 'Escape' || !filtersOpen) return
          setFiltersOpen(false)
          // Focus would otherwise land on <body>, resetting tab order to the
          // top of the page.
          filtersTrigger.current?.focus()
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {/*
            Deliberately outside the collapsing group. Free-text search is the
            control people reach for first, and putting it behind a tap is the
            downgrade the rest of this is trying to avoid.
          */}
          <Input
            label="Search"
            type="search"
            placeholder="Title or description"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />

          {/*
            Between the search box and what it controls, so DOM order, reading
            order and tab order agree. `lg:hidden` is display:none, which
            generates no box at all — so at lg this is not a grid item and the
            five columns line up exactly as they did before. Swap it for
            `lg:invisible` and the row silently gains a sixth cell.
          */}
          <div className="flex items-end lg:hidden">
            <button
              type="button"
              ref={filtersTrigger}
              onClick={() => setFiltersOpen((open) => !open)}
              aria-expanded={filtersOpen}
              aria-controls="job-filters"
              className={buttonClass({ variant: 'secondary', size: 'sm' })}
            >
              <FilterIcon />
              Filters
              {activeFilterCount > 0 && (
                <>
                  {/*
                    The badge is hidden from assistive tech and the count is
                    given as words beside it. A bare "2" in the accessible name
                    reads as "Filters 2", which could be a page number. The
                    visible text stays the name source, so no aria-label is
                    needed and none should be added — it would override the
                    visible text and drift from it.
                  */}
                  <span
                    aria-hidden="true"
                    className="rounded-full bg-indigo-600 px-1.5 text-xs font-semibold text-white"
                  >
                    {activeFilterCount}
                  </span>
                  <span className="sr-only">{activeFilterCount} active</span>
                </>
              )}
            </button>
          </div>

          {/*
            Toggled with display *classes*, not the `hidden` attribute the
            mobile nav in AppLayout uses. Three-way state — collapsed, expanded,
            always-open at lg — is not expressible as one boolean attribute, and
            the attribute would also drop everything in here out of the
            accessibility tree, which is what getByRole filters on.

            The ternary emits exactly one display class. `cn` is a plain join,
            not tailwind-merge, so `cn('grid', !open && 'hidden')` would leave
            both in the attribute and let Tailwind's internal ordering decide.
            `lg:grid` beating a base `hidden` is safe by contrast: it lives in a
            media block, emitted after the base utilities.

            Nothing here may gain `overflow-*`, `transform`, `transition` or a
            stacking context. The experience Combobox's listbox is
            position:absolute with no portal (comboboxCore.listboxClass), so any
            of those clips or re-anchors eleven options. `display` is not
            animatable in any case.
          */}
          <div
            id="job-filters"
            className={cn(
              'gap-4 sm:col-span-2 sm:grid-cols-2 lg:col-span-4 lg:grid-cols-4 lg:grid',
              filtersOpen ? 'grid' : 'hidden',
            )}
          >
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
          <Button variant="secondary" size="sm" className="mt-4" onClick={() => goToOffset(0)}>
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
