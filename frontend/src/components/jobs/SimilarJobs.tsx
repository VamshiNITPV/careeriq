import { useEffect, useState } from 'react'
import { JobCard } from '@/components/JobCard'
import { jobService } from '@/services/jobService'
import type { SimilarJobsResponse } from '@/types/job'

/**
 * Other postings closest to this one, by meaning rather than by keyword.
 *
 * **This section never fails the page.** A rejected request renders nothing at
 * all — no alert, no retry button. Someone reading a job description should not
 * be handed an error box because a side panel could not load, and there is
 * nothing they could do about it anyway.
 *
 * It also renders no heading until there is something under it. "Similar jobs
 * (0)" is noise, and an empty section invites the reader to wonder what they
 * did wrong.
 *
 * **No similarity percentage on the cards.** The API returns one for debugging,
 * but raw cosine needs rescaling before it means anything (ml.md §4.1) and that
 * rescaling is part of the scoring step. Printing an unrescaled 0.71 would put a
 * number on screen that looks like a percentage and is not one.
 */
export function SimilarJobs({ jobId }: { jobId: string }) {
  const [result, setResult] = useState<SimilarJobsResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    // Reset on a job change, so the previous job's neighbours never appear
    // briefly under the new one's heading.
    setResult(null)

    jobService.similar(jobId).then(
      (response) => {
        if (!cancelled) setResult(response)
      },
      () => {
        // Deliberately silent. See the note above.
      },
    )

    return () => {
      cancelled = true
    }
  }, [jobId])

  if (result === null) return null

  if (result.availability === 'DISABLED') return null

  if (result.availability === 'PENDING') {
    return (
      <section aria-labelledby="similar-heading" className="border-t border-slate-200 pt-6">
        <h2 id="similar-heading" className="text-base font-semibold text-slate-900">
          Similar jobs
        </h2>
        {/* Not a spinner: nothing is in flight from the reader's point of view,
            and a spinner that never resolves is worse than a sentence. */}
        <p className="mt-2 text-sm text-slate-600">
          We haven&apos;t indexed this posting yet, so there&apos;s nothing to compare it against.
        </p>
      </section>
    )
  }

  if (result.items.length === 0) return null

  return (
    <section aria-labelledby="similar-heading" className="border-t border-slate-200 pt-6">
      <h2 id="similar-heading" className="text-base font-semibold text-slate-900">
        Similar jobs
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        Closest by what they describe, not by matching words.
      </p>
      {/*
        The existing JobCard, which is why the endpoint returns a full job
        summary including this caller's saved/applied state: the bookmark, the
        tags and the posting age all come for free, and a neighbour behaves
        exactly like a card in the browse list. JobCard derives its own "back to"
        target from the current location, so clicking through and back returns
        here rather than to /jobs.
      */}
      <ul className="mt-3 space-y-3">
        {result.items.map((item) => (
          <JobCard key={item.job.id} job={item.job} />
        ))}
      </ul>
    </section>
  )
}
