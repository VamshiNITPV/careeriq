import { api } from './apiClient'
import type { ApplicationListResponse, ApplicationRead } from '@/types/application'

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
}
