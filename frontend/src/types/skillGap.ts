/** Skill gaps — mirrors backend/app/schemas/skill_gap.py. */

export type GapStatus = 'STRONG' | 'PARTIAL' | 'MISSING'

/**
 * How much a missing skill matters, from how often the target roles ask for it.
 *
 * Deliberately *not* how common the skill is across the whole job corpus. That
 * would say how popular a technology is, not how much it stands between this
 * reader and the jobs they want.
 */
export type GapSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'

export interface SkillGap {
  skill_id: string
  name: string
  category: string
  status: GapStatus
  severity: GapSeverity
  /** Weighted share of the target jobs asking for this, `"0.5400"`. A string
   *  for the reason every fraction in this API is one: floats render badly. */
  frequency: string
  job_count: number
}

export interface SkillGapsResponse {
  items: SkillGap[]
  /**
   * How many postings the report was computed from.
   *
   * Shown, not hidden. Four postings and ninety are very different claims, and
   * a reader who cannot see the denominator will over-read a small sample.
   */
  target_jobs: number
  target_roles: string[]
  job_id: string | null
  /**
   * Why `items` may be empty, when the reason is not "you have no gaps":
   *   NO_TARGET  no target roles set
   *   NO_JOBS    roles set, but nothing live matches them
   */
  availability: 'READY' | 'NO_TARGET' | 'NO_JOBS'
}
