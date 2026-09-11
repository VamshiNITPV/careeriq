import { useCallback, useRef, useState } from 'react'
import { ApiError } from '@/services/apiClient'
import { applicationService } from '@/services/applicationService'
import type { ApplicationRead } from '@/types/application'

/**
 * Saving a job and marking it applied, wherever those controls appear.
 *
 * One hook rather than logic in each surface, because the same three places —
 * a job card, the detail page, a profile row — need identical behaviour, and
 * the detail page shows the controls twice. Two stateful components there would
 * each hold their own pending flag and their own idea of what is saved, and the
 * header and footer would disagree the moment one request was in flight.
 *
 * **Optimistic, and deliberately so.** These are single-bit toggles with nothing
 * to read back from the server. A spinner on a bookmark for a 200 ms round trip
 * reads as broken, and on a slow connection the user taps again — which the
 * idempotent PUT survives, but which a pessimistic UI renders as "nothing
 * happened, try harder". The write is cheap and repeatable, so guessing wrong
 * costs one restored icon and one message: the smallest failure cost here.
 *
 * Contrast `ApplicationLinkForm` in JobDetailPage, which is deliberately *not*
 * optimistic — it changes what every other user sees and can conflict. The two
 * should not be harmonised.
 */
export interface JobApplicationState {
  application: ApplicationRead | null
  isSaved: boolean
  isApplied: boolean
  isPending: boolean
  error: string | null
  toggleSaved: () => void
  setApplied: (applied: boolean) => void
}

function messageOf(caught: unknown): string {
  return caught instanceof ApiError ? caught.message : 'Could not reach the server.'
}

export function useJobApplication(
  jobId: string,
  initial: ApplicationRead | null,
  onChange?: (application: ApplicationRead | null) => void,
): JobApplicationState {
  const [application, setApplication] = useState<ApplicationRead | null>(initial)
  const [isPending, setIsPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // A ref, not the `isPending` state, and not `disabled` on the control. The
  // server is idempotent so this is not protecting data — it stops two
  // responses landing out of order and leaving the icon showing the older one.
  // A control that goes disabled mid-tap is its own irritation.
  const inFlight = useRef(false)

  const commit = useCallback(
    (next: ApplicationRead | null) => {
      setApplication(next)
      onChange?.(next)
    },
    [onChange],
  )

  const run = useCallback(
    async (optimistic: ApplicationRead | null, request: () => Promise<ApplicationRead | null>) => {
      if (inFlight.current) return
      inFlight.current = true
      const previous = application
      setError(null)
      commit(optimistic)
      setIsPending(true)
      try {
        commit(await request())
      } catch (caught) {
        // Put it back. Showing a saved bookmark for a job the server never
        // saved is worse than showing the failure.
        commit(previous)
        setError(messageOf(caught))
      } finally {
        setIsPending(false)
        inFlight.current = false
      }
    },
    [application, commit],
  )

  const saved = application?.is_saved ?? false
  const applied = application?.status === 'APPLIED'

  /**
   * A placeholder so the icon can react before the server answers.
   *
   * The id and created_at are wrong for the moment the request is in flight;
   * nothing reads them in that window, and the real row replaces this the
   * instant it arrives.
   */
  const optimistic = useCallback(
    (next: { saved: boolean; applied: boolean }): ApplicationRead => ({
      id: application?.id ?? 'pending',
      job_id: jobId,
      status: next.applied ? 'APPLIED' : 'SAVED',
      is_saved: next.saved,
      applied_at: next.applied ? new Date().toISOString() : null,
      created_at: application?.created_at ?? new Date().toISOString(),
    }),
    [application, jobId],
  )

  /**
   * Write both flags, or delete the row when neither is left.
   *
   * The server refuses `{saved: false, applied: false}` — a row that records
   * nothing — so "no relationship to this job" goes through DELETE. Deciding
   * that here rather than at each call site means the two toggles cannot
   * disagree about it.
   */
  const write = useCallback(
    (next: { saved: boolean; applied: boolean }) => {
      if (!next.saved && !next.applied) {
        void run(null, async () => {
          await applicationService.remove(jobId)
          return null
        })
        return
      }
      void run(optimistic(next), () => applicationService.set(jobId, next))
    },
    [jobId, optimistic, run],
  )

  // Flips the bookmark and carries `applied` through untouched. Un-bookmarking
  // a job you applied to keeps the applied record and leaves it under
  // Applications — it no longer needs a confirmation, because nothing is lost.
  const toggleSaved = useCallback(() => {
    write({ saved: !saved, applied })
  }, [applied, saved, write])

  // Carries `saved` through untouched, which is the whole fix: this used to
  // send a single status, so recording that you applied also asserted that you
  // had bookmarked the job. Unticking on a job you never bookmarked leaves
  // nothing to record, and `write` deletes the row.
  const setApplied = useCallback(
    (next: boolean) => {
      write({ saved, applied: next })
    },
    [saved, write],
  )

  return {
    application,
    isSaved: saved,
    isApplied: applied,
    isPending,
    error,
    toggleSaved,
    setApplied,
  }
}
