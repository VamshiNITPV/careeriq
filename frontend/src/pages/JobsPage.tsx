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
import {
  EXPERIENCE_YEAR_OPTIONS,
  POSTED_WITHIN_OPTIONS,
  type JobListResponse,
  type JobSummary,
} from '@/types/job'
import { EMPLOYMENT_TYPES, WORK_MODES } from '@/types/profile'
import { cn } from '@/utils/cn'
import {
  clearJobListFilters,
  countActiveJobFilters,
  countPanelFilters,
  MIN_SCORE_OPTIONS,
  PAGE_SIZE,
  readJobListParams,
  setJobListFilter,
  setJobListOffset,
  setJobListSort,
  SORT_OPTIONS,
  type JobFilterKey,
  type JobSort,
} from '@/utils/jobListParams'

/**
 * Browse the job corpus, by date or by how well each posting matches you.
 *
 * **Both orderings live here rather than on two pages.** They were split until
 * Phase 6.5: browse had every filter and no ranking, a separate `/recommendations`
 * page had the ranking and no filters, so "remote Python jobs, best match first"
 * could not be asked for anywhere. Sorting is a property of this list, not a
 * different feature.
 *
 * Match mode makes a claim about the reader, so it says so plainly — scores are
 * shown per row and each links to the breakdown that produced it. It is never
 * the default: an unranked list under a heading implying personalisation would
 * be a claim the system had not made.
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
  // Why a match-sorted list came back empty. Always READY when browsing by date,
  // which cannot fail this way.
  const [availability, setAvailability] =
    useState<JobListResponse['availability']>('READY')

  const [searchParams, setSearchParams] = useSearchParams()

  // Destructured to primitives on purpose. `params` and the object it came from
  // both have a new identity every render, so neither may enter `load`'s
  // dependency array below — that would turn `useEffect(load, [load])` into an
  // unbounded refetch loop, one that would also keep overwriting the in-place
  // row swap `onApplicationChange` performs. `load` depends on the six
  // primitives and nothing else; `params` exists only to be counted.
  const params = readJobListParams(searchParams)
  const { q, workMode, employmentType, yearsValue, postedWithin, offset } = params
  const { sort, minScore, excludeApplied } = params
  const ranked = sort === 'match'

  // What the input shows, versus what the URL holds. Separated so typing stays
  // responsive while requests lag behind it. Seeded from the URL, so arriving
  // at /jobs?q=python shows "python" in the box rather than an empty field
  // sitting over a filtered list.
  const [searchText, setSearchText] = useState(q)
  const [lastQ, setLastQ] = useState(q)

  const requestId = useRef(0)

  // The page opens on a search box and a way to the rest, at every width. The
  // four dropdowns are behind the button, and while they are showing the
  // results are not — filtering is a step, not a thing you do alongside
  // reading.
  //
  // Always closed on arrival, never seeded from the active filters: someone
  // following a shared /jobs?work_mode=REMOTE link came for the results, and
  // opening the panel for them hides the very thing they followed the link
  // for. The count on the button is what tells them a filter is on instead.
  //
  // **`filtersOpen` is written only from onClick/onKeyDown.** It is in no
  // dependency array and no effect writes it. An effect closing it on a filter
  // change is the obvious-looking mistake: Search stays usable while the panel
  // is open, so it would slam shut mid-sentence.
  const [filtersOpen, setFiltersOpen] = useState(false)
  const filtersTrigger = useRef<HTMLButtonElement>(null)

  /*
    Closing always puts focus back on the trigger. The footer button unmounts
    itself, and hiding the panel with display:none blurs whatever is inside it
    — either way focus would land on <body> and reset tab order to the top of
    the page.
  */
  const closeFilters = useCallback(() => {
    setFiltersOpen(false)
    filtersTrigger.current?.focus()
  }, [])

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

  /**
   * Change the ordering. Not `setFilter`, because sort is not a filter.
   *
   * `replace` like the filters: switching order is a change to the current view,
   * not a new place, and pushing would make Back walk through orderings before
   * leaving the page.
   */
  const setSort = useCallback(
    (next: JobSort) =>
      setSearchParams((previous) => setJobListSort(previous, next), { replace: true }),
    [setSearchParams],
  )

  const clearFilters = useCallback(() => {
    // Emptying the box is not redundant, though it looks it: usually the
    // render-phase sync above does it, because `q` changes and the box follows.
    //
    // It does not when the typed term has not settled yet. Type "python" with
    // another filter already on, then clear within the debounce window: `q` is
    // still '' so it does not change, the sync never fires, and 300ms later the
    // debounce writes `?q=python` into the URL that was just cleared.
    setSearchText('')
    setSearchParams(clearJobListFilters, { replace: true })
    // Clearing unmounts the button that was just clicked, because hasFilters
    // goes false. Without this, focus drops to <body>.
    filtersTrigger.current?.focus()
  }, [setSearchParams])

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
        // Sort and its two companions, dropped entirely in browse mode — the
        // API answers 422 to min_score without sort=match, so a stale
        // `?min_score=60` left in the URL would otherwise break the page.
        ...(sort === 'match'
          ? {
              sort: 'match' as const,
              ...(minScore !== '' ? { min_score: Number(minScore) } : {}),
              ...(excludeApplied ? {} : { exclude_applied: false }),
            }
          : {}),
        limit: PAGE_SIZE,
        offset,
      })
      .then(
        (response) => {
          // A slower earlier request must not overwrite a faster later one.
          if (id !== requestId.current) return
          setJobs(response.items)
          setTotal(response.total)
          setAvailability(response.availability)
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
  }, [q, workMode, employmentType, yearsValue, postedWithin, offset, sort, minScore, excludeApplied])

  useEffect(load, [load])

  // Same reason as the request itself. Miss it here and "0+ years" renders
  // "No jobs yet." with an Add-a-job button while a filter is active.
  // Two counts, deliberately. `hasFilters` asks "is the list narrowed at all?"
  // and so includes the search term; the badge asks "how many of the things
  // behind this button are set?" and so does not.
  const hasFilters = countActiveJobFilters(params) > 0
  const panelFilterCount = countPanelFilters(params)

  const showing = jobs.length > 0 ? `${offset + 1}–${offset + jobs.length} of ${total}` : null

  /*
    `total` is the last *completed* load's total, so between a filter change and
    its response this label is one request behind. That staleness is deliberate:
    the alternative is flipping to a placeholder and back on every settled
    keystroke, a flicker on the one control the user is aiming at.

    `total === 0` covers two cases with the same honest words — nothing has
    loaded yet (reachable: the panel can be opened while the mount spinner is
    up) and nothing matches. "Show 0 jobs" reads as a dare.

    On error there is no count to promise, and the button must stay enabled: it
    is the only way back to the "Try again" control.
  */
  /*
    "matches" rather than "jobs" in match mode, and the distinction is factual
    rather than stylistic: a ranked total is capped at the recall limit, so it
    counts the postings that were ranked, not the postings that exist. Calling
    that "200 jobs" on a corpus of 300 would be a number nothing measured.
  */
  const [one, many] = ranked ? ['match', 'matches'] : ['job', 'jobs']
  const showResultsLabel =
    loadState === 'error' || total === 0
      ? 'Show results'
      : total === 1
        ? `Show 1 ${one}`
        : `Show ${total} ${many}`

  /** The prose form, for the live region. Mirrors the "past the end" wording. */
  const totalSentence =
    total === 0
      ? `No ${many} to show.`
      : total === 1
        ? `1 ${one} to show.`
        : `${total} ${many} to show.`

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
          closes this panel. The footer row below is inside this element on
          purpose, so Escape works from the "Show N jobs" button too.
        */
        onKeyDown={(event) => {
          if (event.key !== 'Escape' || !filtersOpen) return
          closeFilters()
        }}
      >
        {/*
          What a closed page offers, at every width: a search box and a way to
          the rest. `flex-wrap` rather than a breakpoint — the button drops to
          its own line exactly when there is no room for it, and `items-end`
          applies per flex line, so the bottoms still align on both.
        */}
        <div className="flex flex-wrap items-end gap-4">
          {/*
            Input renders a bare <div> and forwards className to the <input>
            itself, so the growth has to live on a wrapper of our own.
            `min-w-56` is the width below which the button wraps instead of
            crushing the box.
          */}
          <div className="min-w-56 flex-1">
            <Input
              label="Search"
              type="search"
              placeholder="Title or description"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
            />
          </div>

          {/*
            After the search box and before what it controls, so DOM order,
            reading order and tab order all agree.
          */}
          <button
            type="button"
            ref={filtersTrigger}
            onClick={() => setFiltersOpen((open) => !open)}
            aria-expanded={filtersOpen}
            aria-controls="job-filters"
            className={buttonClass({ variant: 'secondary' })}
          >
            <FilterIcon />
            Filters
            {panelFilterCount > 0 && (
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
                  {panelFilterCount}
                </span>
                <span className="sr-only">{panelFilterCount} active</span>
              </>
            )}
          </button>
        </div>

        {/*
          Toggled with display *classes*, not the `hidden` attribute the mobile
          nav in AppLayout uses. The attribute would drop everything in here out
          of the accessibility tree, which is what getByRole filters on — and
          these four are queried by role and by label throughout
          JobsPage.test.tsx without the panel ever being opened.

          The ternary emits exactly one display class. `cn` is a plain join, not
          tailwind-merge, so `cn('grid', !open && 'hidden')` would leave both in
          the attribute and let Tailwind's internal ordering decide.

          There is no `lg:grid` any more, and there must not be: the panel is
          closed at every width now. `sm:grid-cols-2` and `lg:grid-cols-3` are
          safe in the base string because grid-template-columns does not set
          `display`, so neither can un-hide the panel at a breakpoint.

          Nothing here may gain `overflow-*`, `transform`, `transition`,
          `opacity` or a stacking context. The experience Combobox's listbox is
          position:absolute with no portal (comboboxCore.listboxClass), so any
          of those clips or re-anchors eleven options. `display` is not
          animatable in any case, and plain `grid` is safe — it establishes
          neither a stacking context nor a containing block.
        */}
        <div
          id="job-filters"
          className={cn(
            // Three columns, not four: browse shows five controls and match
            // shows seven, and both divide more evenly by three than the four
            // this had when there were exactly four dropdowns.
            'mt-4 gap-4 sm:grid-cols-2 lg:grid-cols-3',
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
          {/*
            Sort sits with the filters because this is where someone comes to
            change what the list shows, but it is not one of them — no
            placeholder, since "no ordering" is not a state a list can be in, and
            it is excluded from both filter counts and from Clear all.
          */}
          <Select
            label="Sort by"
            options={SORT_OPTIONS}
            value={sort}
            onChange={(e) => setSort(e.target.value as JobSort)}
            hint="Best match ranks every job against your resume."
          />
          {/*
            Only in match mode. Both controls are meaningless over a date-ordered
            list, and rendering them disabled would be four more things to read
            past for a reader who has not asked for ranking at all.
          */}
          {ranked && (
            <Select
              label="Minimum score"
              placeholder="Any score"
              options={MIN_SCORE_OPTIONS}
              value={minScore}
              onChange={(e) => setFilter('min_score', e.target.value)}
            />
          )}
          {ranked && (
            <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={excludeApplied}
                // Written as the string 'false' and deleted when true, so the
                // default state leaves no trace in the URL — one canonical
                // address per view, the same rule every other filter follows.
                onChange={(e) => setFilter('exclude_applied', e.target.checked ? '' : 'false')}
                className="size-4 rounded border-slate-300"
              />
              Hide jobs I&apos;ve applied to
            </label>
          )}
        </div>

        {/*
          Always mounted, and empty while the panel is shut. A live region
          inserted with its text already in place is not reliably announced;
          one whose content changes from '' always is. So opening the panel —
          the moment the results vanish — says what is behind the button, and
          each settled filter change says it again. That is the rate at which
          the "Showing 1–20 of 50" line already announces, so this is parity
          rather than new chatter, and it is what stops a screen-reader user
          losing that line entirely while filtering.

          aria-live with no role, following Combobox.tsx: role="status" would
          collide with the "Showing …" line, and testing-library computes roles
          from the element and its role attribute rather than from aria-live.
        */}
        <span aria-live="polite" className="sr-only">
          {filtersOpen && loadState === 'ready' ? totalSentence : ''}
        </span>

        {/*
          Clear-all stays outside the panel, so clearing is one tap whether the
          panel is open or shut. It stays out of the top row too, though that
          looks like the obvious home: `hasFilters` counts the search term, so
          it would appear 300ms into the first keystroke and shrink the search
          box by its own width, under the user's caret.

          "Show N jobs" is the way back to the results, which otherwise vanish
          with no visible route home. Rendered rather than class-hidden because,
          unlike the four dropdowns, no test needs to reach it while shut.
        */}
        {(hasFilters || filtersOpen) && (
          <div className="mt-4 flex flex-wrap items-center justify-end gap-3">
            {hasFilters && (
              <Button variant="ghost" size="sm" onClick={clearFilters}>
                Clear all filters
              </Button>
            )}
            {filtersOpen && (
              <Button size="sm" onClick={closeFilters}>
                {showResultsLabel}
              </Button>
            )}
          </div>
        )}
      </div>

      {/*
        The results, and everything describing them, only while the panel is
        shut — the error alert included, because "Try again" lives inside the
        chain below and an alert with no way to act on it is half a message.
        The close button falls back to "Show results" whenever loadState is
        'error', so nothing promises a count that is not coming.

        A conditional render, unlike the panel above. That display-class trick
        exists to keep the four dropdowns in jsdom's accessibility tree for
        tests that never open the panel; nothing here needs reaching while the
        panel is open, and unmounting is what was asked for. A fragment, so
        `space-y-6` still sees the alert, the "Showing" line, the <ul> and the
        pager as its own children.
      */}
      {!filtersOpen && (
        <>
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
          ) : availability === 'NO_RESUME' ? (
            /*
              Ranking needs something to rank against. Said plainly, because the
              alternative — an empty list — reads as "no job matches you", which
              is both untrue and far more discouraging than the real problem,
              and gives the reader nothing to act on.
            */
            <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center">
              <p className="text-sm font-medium text-slate-900">
                Upload a resume and we&apos;ll rank every job against it.
              </p>
              <p className="mt-1 text-sm text-slate-600">
                Or switch back to Newest first to browse without one.
              </p>
              <Link to="/resume" className={buttonClass({ className: 'mt-4' })}>
                Upload a resume
              </Link>
            </div>
          ) : availability === 'PENDING' ? (
            <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center">
              <p className="text-sm font-medium text-slate-900">
                We haven&apos;t finished reading your resume yet.
              </p>
              <p className="mt-1 text-sm text-slate-600">
                Check back shortly and your matches will be here.
              </p>
            </div>
          ) : jobs.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center">
              <p className="text-sm font-medium text-slate-900">
                {hasFilters
                  ? `No ${many} match those filters.`
                  : ranked
                    ? // Never "no jobs yet" in match mode: the corpus is not
                      // empty, nothing in it scored well enough.
                      'Nothing matches closely enough to recommend yet.'
                    : 'No jobs yet.'}
              </p>
              <p className="mt-1 text-sm text-slate-600">
                {hasFilters
                  ? 'Try widening the search.'
                  : ranked
                    ? 'More postings arrive daily.'
                    : 'Paste a posting you are interested in to get started.'}
              </p>
              {!hasFilters && !ranked && (
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
                    // A score with no way to see why is a number to be taken on
                    // trust. `footer` rather than a wrapper because JobCard is
                    // the <li>, and wrapping it would nest one inside another.
                    {...(job.match_score !== null
                      ? {
                          footer: (
                            <p className="mt-2 border-t border-slate-100 pt-2 text-xs text-slate-500">
                              Match score {job.match_score} / 100 &middot;{' '}
                              <Link to={`/jobs/${job.id}`} className="relative z-10 underline">
                                see why
                              </Link>
                            </p>
                          ),
                        }
                      : {})}
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
        </>
      )}
    </div>
  )
}
