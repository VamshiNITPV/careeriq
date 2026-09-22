/** Saved jobs and the applied flag — mirrors backend/app/schemas/application.py. */

import type { JobSummary } from '@/types/job'

/** All seven. The funnel that reads them arrived with US-7.1. */
export type ApplicationStatus =
  | 'SAVED'
  | 'APPLIED'
  | 'ASSESSMENT'
  | 'INTERVIEW'
  | 'OFFER'
  | 'REJECTED'
  | 'WITHDRAWN'

/**
 * The funnel in order, mirroring `services/application/lifecycle.py`.
 *
 * Order only — **not** the transition rules. Which moves are allowed is the
 * server's answer, and a 409 carries `details.allowed` precisely so this file
 * never has to hold a second copy of those rules that can drift from the first.
 */
export const FUNNEL: readonly ApplicationStatus[] = [
  'SAVED',
  'APPLIED',
  'ASSESSMENT',
  'INTERVIEW',
  'OFFER',
]

/** Where an application stops. Reachable from any active stage. */
export const TERMINAL: readonly ApplicationStatus[] = ['REJECTED', 'WITHDRAWN']

export const STATUS_LABEL: Record<ApplicationStatus, string> = {
  SAVED: 'Saved',
  APPLIED: 'Applied',
  ASSESSMENT: 'Assessment',
  INTERVIEW: 'Interview',
  OFFER: 'Offer',
  REJECTED: 'Rejected',
  WITHDRAWN: 'Withdrawn',
}

/**
 * Full class strings, never built by interpolation.
 *
 * Tailwind v4 scans source *text* for class names, so a template literal like
 * `bg-${tone}-100` produces a class that exists at runtime and was never
 * compiled into the stylesheet — it fails silently as unstyled output.
 */
export const STATUS_TONE: Record<ApplicationStatus, string> = {
  SAVED: 'bg-slate-100 text-slate-700',
  APPLIED: 'bg-sky-100 text-sky-800',
  ASSESSMENT: 'bg-violet-100 text-violet-800',
  INTERVIEW: 'bg-amber-100 text-amber-900',
  OFFER: 'bg-emerald-100 text-emerald-800',
  REJECTED: 'bg-rose-100 text-rose-800',
  WITHDRAWN: 'bg-stone-200 text-stone-700',
}

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
  /**
   * When you say you applied. Null while the row is only a bookmark.
   *
   * A database CHECK ties this to `status`: null at SAVED, set for every stage
   * past it, unconstrained once rejected or withdrawn — an application can stop
   * before it was ever sent.
   */
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
