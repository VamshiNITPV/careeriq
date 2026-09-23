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
 *
 * The 50/700/600-20 ring-inset triple is the app's pill palette, matching
 * `SkillGapsPage`'s severity and status pills. These were flat `bg-X-100` in
 * the first version of this screen, which is why it read as belonging to a
 * different application than the rest.
 */
export const STATUS_TONE: Record<ApplicationStatus, string> = {
  SAVED: 'bg-slate-100 text-slate-600 ring-slate-500/20',
  APPLIED: 'bg-sky-50 text-sky-700 ring-sky-600/20',
  ASSESSMENT: 'bg-violet-50 text-violet-700 ring-violet-600/20',
  INTERVIEW: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  OFFER: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  REJECTED: 'bg-red-50 text-red-700 ring-red-600/20',
  WITHDRAWN: 'bg-slate-100 text-slate-600 ring-slate-500/20',
}

/**
 * The filled portion of each stage's bar in the funnel summary.
 *
 * Separate from `STATUS_TONE` because a pill's background and a bar's fill want
 * opposite weights: the pill is a tint behind text, the bar is a solid mark
 * read on its own. Reusing the pill's 50-shade here drew bars that were
 * invisible against the slate-100 track.
 */
export const STATUS_FILL: Record<ApplicationStatus, string> = {
  SAVED: 'bg-slate-400',
  APPLIED: 'bg-sky-500',
  ASSESSMENT: 'bg-violet-500',
  INTERVIEW: 'bg-amber-500',
  OFFER: 'bg-emerald-500',
  REJECTED: 'bg-red-400',
  WITHDRAWN: 'bg-slate-300',
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

/** One slice of the funnel (US-7.2). Mirrors schemas/application_analytics.py. */
export interface FunnelSegment {
  label: string
  applications: number
  interviews: number
  offers: number
  /**
   * Fraction, not a percentage, and **null is not zero**.
   *
   * Null means "too few applications to say" — the server withholds a rate
   * below `min_for_rate`. `0` means "enough of them, and none reached it",
   * which is a real answer. Rendering the two the same way would turn "we do
   * not know" into "you failed".
   */
  interview_rate: number | null
  offer_rate: number | null
  low_confidence: boolean
}

export interface FunnelAnalyticsResponse {
  overall: FunnelSegment
  by_role: FunnelSegment[]
  by_location: FunnelSegment[]
  /**
   * Which resume was sent, and how well it scored at the time.
   *
   * Both read a snapshot taken when the application was sent, because neither
   * survives being asked for later — a resume gets edited and the corpus moves,
   * so recomputing would answer "how well would this match today". Rows sent
   * before that snapshot existed appear under "Not recorded" rather than being
   * dropped, so these still add up to `overall.applications`.
   */
  by_resume: FunnelSegment[]
  by_score_band: FunnelSegment[]
  /** The threshold the server applied, so this side need not hold a copy. */
  min_for_rate: number
  /** Which of US-7.2 AC2's slices this build answers. All four, since 0020. */
  segments_available: string[]
}
