export type AnalysisStatus = 'PENDING' | 'RUNNING' | 'COMPLETE' | 'FAILED'
export type SuggestionDecision = 'PENDING' | 'ACCEPTED' | 'REJECTED'

export interface Suggestion {
  id: string
  position: number
  section: string
  /** The resume text this replaces, copied exactly. */
  original: string
  suggested: string
  rationale: string
  /**
   * Source lines the model cited.
   *
   * Shown so a reader can check the rewrite against their own resume. Evidence,
   * not proof — nothing stops a model citing a line that does not support its
   * claim, which is why the server re-reads the resume itself.
   */
  grounded_in: string[]
  decision: SuggestionDecision
  decided_at: string | null
}

export interface AnalysisResponse {
  analysis_id: string
  resume_version_id: string
  job_id: string
  status: AnalysisStatus
  /** Present only when FAILED, and then always. */
  error: string | null
  suggestions: Suggestion[]
  /** Discarded for inventing something the resume does not say. */
  rejected_by_validator: number
  /** Discarded for arriving in the wrong shape. A different problem. */
  dropped_malformed: number
  completed_at: string | null
}

export interface AnalyzeStarted {
  analysis_id: string
  status: AnalysisStatus
  poll_url: string
}

export interface ApplyResult {
  resume_version_id: string
  /** Carried so the success screen can link straight at the new version. */
  resume_id: string
  version_number: number
  applied: number
  rejected: number
  message: string
}
