import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { JobCard } from '@/components/JobCard'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { jobService } from '@/services/jobService'
import type { RecommendationsResponse } from '@/types/job'

const PAGE_SIZE = 10

/** The `min_score` choices, as scores a reader can reason about. */
const SCORE_FILTERS = [
  { label: 'Any score', value: undefined },
  { label: '50 and above', value: 50 },
  { label: '60 and above', value: 60 },
  { label: '70 and above', value: 70 },
] as const

/**
 * The full ranked list, with the filters the API has always supported.
 *
 * The dashboard panel shows five and is a prompt; this is the page you come to
 * when you want to work through everything. It exposes `min_score` and
 * `exclude_applied`, which have been live query parameters since Phase 6.3 with
 * no interface — the endpoint could do this and nothing asked it to.
 *
 * Unlike the dashboard panel, this page **does** show errors. A panel that fails
 * quietly is the right call when it sits beside other content the reader came
 * for; a page whose whole purpose failed has to say so, or it reads as "no jobs
 * match you", which is a different and much more discouraging claim.
 */
export function RecommendationsPage() {
  const [result, setResult] = useState<RecommendationsResponse | null>(null)
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading')

  // Cursors only go forwards, so Previous is client-side history — the same
  // stack RecommendedJobs keeps. `cursors[i]` fetches page i, starting at null.
  const [cursors, setCursors] = useState<(string | null)[]>([null])
  const [page, setPage] = useState(0)
  const [turning, setTurning] = useState<'prev' | 'next' | null>(null)

  const [minScore, setMinScore] = useState<number | undefined>(undefined)
  const [excludeApplied, setExcludeApplied] = useState(true)

  // Compared after the await, so a superseded response is dropped rather than
  // overwriting a newer page. A boolean per effect run cannot tell which
  // response is current — only that it is not the one this run started.
  const requestId = useRef(0)

  const load = useCallback(
    (target: number, cursor: string | null) => {
      const id = ++requestId.current
      if (target === 0 && cursor === null) setLoadState('loading')
      return jobService
        .recommendations({
          limit: PAGE_SIZE,
          ...(cursor !== null ? { cursor } : {}),
          ...(minScore !== undefined ? { minScore } : {}),
          excludeApplied,
        })
        .then(
          (response) => {
            if (id !== requestId.current) return
            setResult(response)
            setPage(target)
            setTurning(null)
            setLoadState('ready')
          },
          () => {
            if (id !== requestId.current) return
            setTurning(null)
            // Only a first load becomes a page-level error. A failed page turn
            // keeps the rows already on screen — blanking them would lose the
            // reader's place over something they cannot act on.
            setLoadState((current) => (current === 'ready' ? 'ready' : 'error'))
          },
        )
    },
    [minScore, excludeApplied],
  )

  // Changing a filter is a new ranking, so paging restarts from the first page.
  // Keeping the cursor would resume partway through a list that no longer exists.
  useEffect(() => {
    setCursors([null])
    void load(0, null)
  }, [load])

  const goNext = () => {
    const next = result?.next_cursor
    if (next === undefined || next === null) return
    setTurning('next')
    setCursors((previous) => [...previous.slice(0, page + 1), next])
    void load(page + 1, next)
  }

  const goPrevious = () => {
    if (page === 0) return
    setTurning('prev')
    void load(page - 1, cursors[page - 1] ?? null)
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Recommended for you</h1>
        <p className="mt-1 text-sm text-slate-600">
          Every open job, ranked against your resume rather than matched on keywords.
        </p>
      </header>

      <section
        aria-labelledby="filters-heading"
        className="rounded-xl border border-slate-200 bg-white p-4"
      >
        <h2 id="filters-heading" className="sr-only">
          Filters
        </h2>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <label className="flex items-center gap-2 text-sm text-slate-700">
            Minimum score
            <select
              value={minScore ?? ''}
              onChange={(event) =>
                setMinScore(event.target.value === '' ? undefined : Number(event.target.value))
              }
              className="rounded-md border border-slate-300 px-2 py-1 text-sm"
            >
              {SCORE_FILTERS.map((option) => (
                <option key={option.label} value={option.value ?? ''}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={excludeApplied}
              onChange={(event) => setExcludeApplied(event.target.checked)}
              className="size-4 rounded border-slate-300"
            />
            Hide jobs I&apos;ve applied to
          </label>
        </div>
      </section>

      {loadState === 'error' ? (
        <Alert tone="error">
          We couldn&apos;t load your recommendations. This is a problem on our side, not a sign that
          nothing matches you.
        </Alert>
      ) : loadState === 'loading' ? (
        <div className="flex justify-center py-12">
          <Spinner className="size-6 text-indigo-600" label="Loading your recommendations" />
        </div>
      ) : result === null ? null : result.availability === 'NO_RESUME' ? (
        <section className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6">
          <p className="text-sm text-slate-600">
            Upload a resume and we&apos;ll rank every open job against it.
          </p>
          <Link
            to="/resume"
            className="mt-3 inline-block rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
          >
            Upload a resume
          </Link>
        </section>
      ) : result.availability === 'PENDING' ? (
        <section className="rounded-xl border border-slate-200 bg-white p-6">
          <p className="text-sm text-slate-600">
            We haven&apos;t finished reading your resume yet. Check back shortly and your matches
            will be here.
          </p>
        </section>
      ) : result.items.length === 0 ? (
        <section className="rounded-xl border border-slate-200 bg-white p-6">
          <p className="text-sm text-slate-600">
            {minScore === undefined
              ? 'Nothing in the current job list matches closely enough to recommend yet.'
              : `No jobs scored ${minScore} or above. Try a lower minimum.`}
          </p>
        </section>
      ) : (
        <>
          {/* JobCard is the list item, so the score goes in its footer slot —
              wrapping it would nest one <li> inside another. */}
          <ul className="space-y-3">
            {result.items.map((item) => (
              <JobCard
                key={item.job.id}
                job={item.job}
                footer={
                  <p className="mt-2 border-t border-slate-100 pt-2 text-xs text-slate-500">
                    Match score {item.score} / 100 &middot;{' '}
                    <Link to={`/jobs/${item.job.id}`} className="relative z-10 underline">
                      see why
                    </Link>
                  </p>
                }
              />
            ))}
          </ul>

          {/* Both controls stay mounted and disable at the ends: hiding the one
              just clicked drops focus to <body>. Same rule as JobsPage. */}
          <div className="flex items-center justify-between border-t border-slate-200 pt-4">
            <Button
              variant="secondary"
              size="sm"
              disabled={page === 0}
              isLoading={turning === 'prev'}
              onClick={goPrevious}
            >
              Previous
            </Button>
            <p className="text-xs text-slate-500">Page {page + 1}</p>
            <Button
              variant="secondary"
              size="sm"
              disabled={result.next_cursor === null}
              isLoading={turning === 'next'}
              onClick={goNext}
            >
              Next
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
