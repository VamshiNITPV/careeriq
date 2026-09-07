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
  /** Non-null while the confirm-before-losing-an-applied-record dialog is open. */
  pendingUnsave: ApplicationRead | null
  dialogError: string | null
  toggleSaved: () => void
  setApplied: (applied: boolean) => void
  confirmUnsave: () => Promise<void>
  cancelUnsave: () => void
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
  const [pendingUnsave, setPendingUnsave] = useState<ApplicationRead | null>(null)
  const [dialogError, setDialogError] = useState<string | null>(null)

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

  /**
   * A placeholder so the icon can fill before the server answers.
   *
   * The id and created_at are wrong for the moment the request is in flight;
   * nothing reads them in that window, and the real row replaces this the
   * instant it arrives.
   */
  const optimistic = useCallback(
    (status: 'SAVED' | 'APPLIED'): ApplicationRead => ({
      id: application?.id ?? 'pending',
      job_id: jobId,
      status,
      applied_at: status === 'APPLIED' ? new Date().toISOString() : null,
      created_at: application?.created_at ?? new Date().toISOString(),
    }),
    [application, jobId],
  )

  const toggleSaved = useCallback(() => {
    if (application === null) {
      void run(optimistic('SAVED'), () => applicationService.set(jobId, 'SAVED'))
      return
    }
    if (application.status === 'APPLIED') {
      // No request yet. Losing the record that you applied is worth one
      // confirmation, and a stray tap on a phone is exactly how it would go.
      setPendingUnsave(application)
      setDialogError(null)
      return
    }
    void run(null, async () => {
      await applicationService.remove(jobId)
      return null
    })
  }, [application, jobId, optimistic, run])

  const setApplied = useCallback(
    (applied: boolean) => {
      // Unticking sends SAVED, never a delete: the job stays saved. Ticking a
      // job that was never saved creates the row directly in APPLIED, because
      // applied implies saved and there is only ever one row.
      const status = applied ? 'APPLIED' : 'SAVED'
      void run(optimistic(status), () => applicationService.set(jobId, status))
    },
    [jobId, optimistic, run],
  )

  const confirmUnsave = useCallback(async () => {
    setIsPending(true)
    setDialogError(null)
    try {
      await applicationService.remove(jobId)
      commit(null)
      setPendingUnsave(null)
    } catch (caught) {
      // The dialog stays open and says so. Its message must render inside the
      // dialog: showModal() makes the rest of the document inert, so a
      // page-level alert would sit behind the backdrop, invisible.
      setDialogError(messageOf(caught))
    } finally {
      setIsPending(false)
    }
  }, [commit, jobId])

  const cancelUnsave = useCallback(() => {
    setPendingUnsave(null)
    setDialogError(null)
  }, [])

  return {
    application,
    isSaved: application !== null,
    isApplied: application?.status === 'APPLIED',
    isPending,
    error,
    pendingUnsave,
    dialogError,
    toggleSaved,
    setApplied,
    confirmUnsave,
    cancelUnsave,
  }
}
