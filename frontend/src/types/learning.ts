/** Learning paths — mirrors backend/app/schemas/learning.py. */

export interface LearningStep {
  position: number
  skill_id: string
  name: string
  severity: string
  /**
   * Rough study hours for someone who already meets the prerequisites.
   *
   * An estimate, and the interface must present it as one. There is no dataset
   * of how long people take to learn things; the numbers are ordered sensibly
   * against each other, which is what sequencing needs, and claim nothing about
   * absolute accuracy.
   */
  estimated_hours: number
  /** Something you can check you have done — never a restatement of the name. */
  outcome: string
  /** Steps in this same plan that must come first, by name. */
  after: string[]
  completed: boolean
}

export interface LearningPathResponse {
  steps: LearningStep[]
  total_hours: number
  /** Hours left once finished steps are discounted. */
  remaining_hours: number
  target_jobs: number
  target_roles: string[]
  job_id: string | null
  /** Missing skills with no curated guidance — reported, not invented over. */
  skipped_uncurated: number
  availability: 'READY' | 'NO_TARGET' | 'NO_JOBS'
}
