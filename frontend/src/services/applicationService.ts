import { api } from './apiClient'
import type {
  ApplicationListResponse,
  ApplicationRead,
  ApplicationStatus,
} from '@/types/application'

export const applicationService = {
  /**
   * Set your whole relationship to a job: bookmarked, applied, or both.
   *
   * **Both flags every time.** They are independent, and the body is the
   * complete desired state — so a caller marking a job applied passes the
   * bookmark state it already holds, and recording one fact can never rewrite
   * the other by omission.
   *
   * `{saved: false, applied: false}` is a 422. That is `remove()`.
   *
   * Idempotent by construction — PUT on a singleton sub-resource, upserted
   * server-side on a unique index — so a double tap on a phone is the same
   * write rather than a conflict.
   */
  set(jobId: string, state: { saved: boolean; applied: boolean }): Promise<ApplicationRead> {
    return api.put<ApplicationRead>(`/jobs/${jobId}/application`, state)
  },

  /** Drop the job from your lists entirely. 204 whether or not there was a row. */
  remove(jobId: string): Promise<void> {
    return api.delete<void>(`/jobs/${jobId}/application`)
  },

  /**
   * Everything saved or applied, newest first.
   *
   * The profile page asks for all of them and splits the two lists locally
   * rather than making two filtered requests: entries move between the lists,
   * and two responses could disagree and leave a row in both or in neither.
   */
  list(): Promise<ApplicationListResponse> {
    return api.get<ApplicationListResponse>('/applications')
  },

  /**
   * Move one application to another stage.
   *
   * **Not idempotent**, unlike `set` above, and deliberately so: asking to move
   * to the stage it is already in is a 409, because staying put is not a
   * transition and an event recording that nothing happened is noise in a log
   * whose whole worth is the opposite.
   *
   * A refused move throws `ApiError` with code `INVALID_STATUS_TRANSITION` and
   * `details.allowed` listing where it can actually go — so a caller recovers
   * from the server's answer rather than keeping its own copy of the rules.
   *
   * `occurredAt` is for moves reported after the fact, which is most of them:
   * people log an interview the evening after it. Omitted means now. The server
   * refuses a future time.
   */
  changeStatus(
    applicationId: string,
    status: ApplicationStatus,
    occurredAt?: string,
  ): Promise<ApplicationRead> {
    return api.patch<ApplicationRead>(`/applications/${applicationId}/status`, {
      status,
      ...(occurredAt === undefined ? {} : { occurred_at: occurredAt }),
    })
  },
}
