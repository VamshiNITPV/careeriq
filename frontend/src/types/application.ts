/** Saved jobs and the applied flag — mirrors backend/app/schemas/application.py. */

import type { JobSummary } from '@/types/job'

/**
 * Two members, not the seven the full lifecycle sketches. Assessment, interview,
 * offer, rejected and withdrawn arrive with the funnel that reads them.
 */
export type ApplicationStatus = 'SAVED' | 'APPLIED'

export interface ApplicationRead {
  id: string
  job_id: string
  status: ApplicationStatus
  /**
   * Whether you bookmarked this job.
   *
   * Independent of `status` — a job can be bookmarked, applied to, or both.
   * **Read this for the bookmark icon**, never "does an application exist":
   * doing the latter is what made ticking "I have applied" fill the bookmark.
   */
  is_saved: boolean
  /** Non-null exactly when status is APPLIED — a database CHECK enforces it. */
  applied_at: string | null
  /** When it was saved. Orders the profile lists. */
  created_at: string
}

export interface ApplicationListItem extends ApplicationRead {
  /** Its `application` is always null: this row already is the application. */
  job: JobSummary
}

export interface ApplicationListResponse {
  items: ApplicationListItem[]
  total: number
}
