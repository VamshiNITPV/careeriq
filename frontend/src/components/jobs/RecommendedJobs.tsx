import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { JobCard } from '@/components/JobCard'
import { Button } from '@/components/ui/Button'
import { useJobBackState } from '@/hooks/useJobBackState'
import { jobService } from '@/services/jobService'
import type { RecommendationsResponse } from '@/types/job'

/**
 * Jobs ranked for this user, on the dashboard.
 *
 * The inversion Phase 6.3 is for: until now a score only appeared once someone
 * had already found a job themselves, which is backwards — the point of scoring
 * is to surface work they would not have thought to search for.
 *
 * **Every state says something.** An empty list has three causes needing three
 * different answers, so `availability` is rendered rather than collapsed:
 * `NO_RESUME` asks for an upload, `PENDING` explains that indexing has not
 * caught up, and `READY` with nothing in it means the corpus genuinely holds
 * nothing close enough. A single "no matches" for all three would send a user
 * hunting for a problem that is not theirs.
 *
 * The score is shown, the breakdown is not. Six rows per card across five cards
 * is not a summary, it is a wall — the full explanation lives one click away on
 * the job page, which is where someone reads it once they have decided a job is
 * worth the time.
 *
 * ## Paging
 *
 * The server ranks its whole recall set (~200 postings) and hands back one page
 * plus a `next_cursor`. There is no `prev_cursor`, and there should not be: the
 * token means "resume strictly after this `(score, job_id)`", which only moves
 * one way. So **Previous is client-side history** — `cursors[i]` is the cursor
 * that fetches page `i`, starting with `null` for the first page, and going back
 * is a refetch with a cursor we already hold rather than a new kind of request.
 *
 * Keeping the *cursors* rather than the *items* is deliberate. Caching pages
 * would serve stale scores after the user edits their profile in another tab,
 * which is exactly the staleness 6.3 avoided by not caching server-side either.
 */
export function RecommendedJobs({ limit = 5 }: { limit?: number }) {
  // So "see why" returns to the dashboard rather than to the job list, which is
  // not where the reader was.
  const backState = useJobBackState()
  const [result, setResult] = useState<RecommendationsResponse | null>(null)
  //: `cursors[i]` fetches page `i`. `null` is the first page — no cursor at all.
  const [cursors, setCursors] = useState<(string | null)[]>([null])
  const [page, setPage] = useState(0)
  const [turning, setTurning] = useState<'prev' | 'next' | null>(null)

  /*
   * A request id rather than a `cancelled` flag per effect run. Two quick taps
   * on Next resolve in whatever order the network decides, and a boolean scoped
   * to one effect cannot tell which response is the current one — it can only
   * say "not mine", which is true of both. Compared after the await, so a
   * superseded response is dropped instead of overwriting a newer page.
   */
  const requestId = useRef(0)

  const load = useCallback(
    (target: number, cursor: string | null) => {
      const id = ++requestId.current
      return jobService.recommendations(cursor === null ? { limit } : { limit, cursor }).then(
        (response) => {
          if (id !== requestId.current) return
          setResult(response)
          setPage(target)
          setTurning(null)
        },
        () => {
          if (id !== requestId.current) return
          /*
           * Silent, like the other dashboard panels. On the first load that
           * means rendering nothing at all; on a page turn it means leaving the
           * rows that are already on screen and re-enabling the buttons, which
           * beats blanking a panel over a failure the reader cannot act on.
           */
          setTurning(null)
        },
      )
    },
    [limit],
  )

  useEffect(() => {
    void load(0, null)
  }, [load])

  const goNext = () => {
    const next = result?.next_cursor
    if (next === undefined || next === null) return
    setTurning('next')
    /*
     * `page` is the single source of truth for which cursor to use, so this
     * write is housekeeping rather than a correctness guard: truncating at the
     * current page stops the array accumulating a stale forward history as
     * someone walks back and forth. Nothing below `page` ever changes, which is
     * why `goPrevious` can index it directly.
     */
    setCursors((previous) => [...previous.slice(0, page + 1), next])
    void load(page + 1, next)
  }

  const goPrevious = () => {
    if (page === 0) return
    setTurning('prev')
    void load(page - 1, cursors[page - 1] ?? null)
  }

  if (result === null) return null

  if (result.availability === 'NO_RESUME') {
    return (
      <Section>
        <p className="text-sm text-slate-600">
          Upload a resume and we&apos;ll rank open jobs against it, highest fit first.
        </p>
        <Link
          to="/resume"
          className="mt-3 inline-block rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
        >
          Upload a resume
        </Link>
      </Section>
    )
  }

  if (result.availability === 'PENDING') {
    return (
      <Section>
        {/* Not a spinner. Nothing is in flight from the reader's point of view,
            and a spinner that never resolves is worse than a sentence. */}
        <p className="text-sm text-slate-600">
          We haven&apos;t finished reading your resume yet. Check back shortly and your matches will
          be here.
        </p>
      </Section>
    )
  }

  if (result.items.length === 0) {
    return (
      <Section>
        <p className="text-sm text-slate-600">
          Nothing in the current job list matches closely enough to recommend yet.
        </p>
      </Section>
    )
  }

  return (
    <Section>
      {/* JobCard *is* the list item, so the score goes in its footer slot rather
          than in a wrapper — a wrapper would nest one <li> inside another. */}
      <ul className="space-y-3">
        {result.items.map((item) => (
          <JobCard
            key={item.job.id}
            job={item.job}
            footer={
              <p className="mt-2 border-t border-slate-100 pt-2 text-xs text-slate-500">
                Match score {item.score} / 100 &middot;{' '}
                <Link
                  to={`/jobs/${item.job.id}`}
                  state={backState}
                  className="relative z-10 underline"
                >
                  see why
                </Link>
              </p>
            }
          />
        ))}
      </ul>

      {/*
        Both buttons stay mounted and disable, rather than one of them
        disappearing at each end. Hiding the control the reader just clicked
        drops focus to <body> — the reason JobsPage prefers `disabled` to
        conditional rendering too.

        `Next` is shown even on a single page, where it is simply disabled: the
        alternative is a control that appears only once there is a second page,
        which reads as the interface changing shape for no visible reason.
      */}
      <div className="mt-4 flex items-center justify-between border-t border-slate-200 pt-4">
        <Button
          variant="secondary"
          size="sm"
          disabled={page === 0}
          isLoading={turning === 'prev'}
          onClick={goPrevious}
        >
          Previous
        </Button>

        {/*
          "Page 2", not "6-10 of 200". `considered` is the size of the recall
          set and score filtering happens after it server-side, so any total
          derived from it is exact only while this panel sends no `min_score`.
          A number that is right by coincidence of the current configuration is
          the kind that goes quietly wrong later.
        */}
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

      {/*
        Announced separately because the visible indicator is ordinary text, and
        a second role="status" on the dashboard would compete with the ones
        already there. No role attribute, and it renders '' until there is
        something to say — a live region inserted with its text already in place
        is not reliably announced, one whose content changes always is.
      */}
      <span aria-live="polite" className="sr-only">
        {page === 0 ? '' : `Page ${page + 1} of recommendations`}
      </span>
    </Section>
  )
}

function Section({ children }: { children: React.ReactNode }) {
  return (
    <section
      aria-labelledby="recommended-heading"
      className="rounded-xl border border-slate-200 bg-white p-4 sm:p-6"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4">
        <h2 id="recommended-heading" className="text-base font-semibold text-slate-900">
          Recommended for you
        </h2>
        {/*
          The way to the full ranking, and the only one since Phase 6.5 folded
          "Matches" into the Jobs page — this panel shows five and is a prompt,
          so without it the rest of the ranking has no entry point at all.
        */}
        <Link to="/jobs?sort=match" className="text-sm font-medium text-indigo-600 hover:underline">
          See all matches
        </Link>
      </div>
      <p className="mt-1 mb-3 text-sm text-slate-600">
        Ranked against your resume, not by keyword.
      </p>
      {children}
    </section>
  )
}
