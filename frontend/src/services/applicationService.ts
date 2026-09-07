import { api } from './apiClient'
import type {
  ApplicationListResponse,
  ApplicationRead,
  ApplicationStatus,
} from '@/types/application'

export const applicationService = {
  /**
   * Save a job, or record that you applied to it.
   *
   * Idempotent by construction — PUT on a singleton sub-resource, upserted
   * server-side on a unique index — so a double tap on a phone is the same
   * write rather than a conflict. Unmarking applied sends `SAVED`, not a
   * delete: the job stays saved.
   */
  set(jobId: string, status: ApplicationStatus): Promise<ApplicationRead> {
    return api.put<ApplicationRead>(`/jobs/${jobId}/application`, { status })
  },

  /** Unsave. 204 whether or not there was anything to remove. */
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
