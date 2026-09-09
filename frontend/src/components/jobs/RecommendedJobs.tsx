import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { JobCard } from '@/components/JobCard'
import { jobService } from '@/services/jobService'
import type { RecommendationsResponse } from '@/types/job'

/**
 * Jobs ranked for this user, on the dashboard.
 *
 * The inversion this phase is for: until now a score only appeared once someone
 * had already found a job themselves, which is backwards — the point of scoring
 * is to surface work they would not have thought to search for.
 *
 * **Every state says something.** An empty list has three causes and they need
 * three different answers, so `availability` is rendered rather than collapsed:
 * `NO_RESUME` asks for an upload, `PENDING` explains that indexing has not
 * caught up, and `READY` with nothing in it means the corpus genuinely holds
 * nothing yet. A single "no matches" for all three would send a user hunting for
 * a problem that is not theirs.
 *
 * The score is shown, the breakdown is not. Six rows per card across ten cards
 * is not a summary, it is a wall — the full explanation lives one click away on
 * the job page, which is where someone reads it when they have decided a job is
 * worth the time.
 */
export function RecommendedJobs({ limit = 5 }: { limit?: number }) {
  const [result, setResult] = useState<RecommendationsResponse | null>(null)

  useEffect(() => {
    let cancelled = false

    jobService.recommendations({ limit }).then(
      (response) => {
        if (!cancelled) setResult(response)
      },
      () => {
        // Silent, like the other panels. A dashboard that shows an error box
        // because one section could not load is worse than one without it.
      },
    )

    return () => {
      cancelled = true
    }
  }, [limit])

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
      {/* JobCard *is* the list item, so the score goes in its footer slot
          rather than in a wrapper — a wrapper would nest one <li> inside
          another, which is invalid and which React says so about. */}
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
    </Section>
  )
}

function Section({ children }: { children: React.ReactNode }) {
  return (
    <section
      aria-labelledby="recommended-heading"
      className="rounded-xl border border-slate-200 bg-white p-6"
    >
      <h2 id="recommended-heading" className="text-base font-semibold text-slate-900">
        Recommended for you
      </h2>
      <p className="mt-1 mb-3 text-sm text-slate-600">
        Ranked against your resume, not by keyword.
      </p>
      {children}
    </section>
  )
}
