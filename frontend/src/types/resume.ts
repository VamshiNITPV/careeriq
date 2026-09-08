/** Resume types mirroring backend/app/schemas/resume.py. */

export type ProcessingStatus =
  | 'PENDING'
  | 'EXTRACTING'
  | 'PARSING'
  | 'EMBEDDING'
  | 'COMPLETE'
  | 'FAILED'

export type ProficiencyLevel = 'BEGINNER' | 'INTERMEDIATE' | 'ADVANCED' | 'EXPERT'

export interface ResumeVersionSummary {
  id: string
  version_number: number
  original_filename: string
  mime_type: string
  file_size_bytes: number
  processing_status: ProcessingStatus
  processing_error: string | null
  processed_at: string | null
  created_at: string
}

export interface Resume {
  id: string
  title: string
  is_primary: boolean
  /**
   * The last version that parsed *successfully*. Null while the first parse
   * runs, and null forever if every parse failed. This is the version to ask
   * for suggestions.
   */
  current_version_id: string | null
  created_at: string
  updated_at: string
  /** Skills traceable to this resume, removed along with it. */
  skill_count: number
  /**
   * The most recent upload, successful or not — the version to re-parse.
   * Distinct from `current_version_id`: a failed parse never becomes current,
   * so without this a failed resume is indistinguishable from an empty one and
   * there is nothing to retry against.
   */
  latest_version_id: string | null
  latest_version_status: ProcessingStatus | null
  latest_version_error: string | null
}

/**
 * One heading the extractor found, from `parsed_sections.sections`.
 *
 * `start`, `end` and `length` are character offsets into `raw_text`. They are
 * carried for completeness and deliberately not rendered anywhere — they mean
 * nothing to a reader.
 */
export interface ParsedSection {
  type: string
  heading: string | null
  start: number
  end: number
  length: number
}

/**
 * `ResumeVersion.parsed_sections`, written by the pipeline.
 *
 * **Every key is optional, and that is the defence.** This is `dict[str, Any]`
 * on the server, and the JSONB in any given row was written by whatever version
 * of the pipeline was deployed at the time — so a key added later is simply
 * absent from an older row. A required field would be a lie the compiler
 * enforces. Narrow at the point of use: `parsed_sections?.sections ?? []`.
 */
export interface ParsedSections {
  extractor?: string
  page_count?: number | null
  character_count?: number
  sections?: ParsedSection[]
}

export interface ParsedSkill {
  name: string
  /**
   * A JSON **number**, unlike `SuggestedSkill.confidence` below, which is a
   * string. That one goes through Pydantic's Decimal and serialises quoted;
   * this one is a raw float dumped into JSONB by the pipeline. Getting the two
   * the wrong way round renders `NaN%` with no type error to warn you.
   */
  confidence: number
  mentions: number
  section: string
  matched: string[]
  span: number[]
  /** False when the parse wanted a human to confirm it. */
  accepted: boolean
}

/** `ResumeVersion.parsed_entities`. Optional keys for the reason above. */
export interface ParsedEntities {
  skills?: ParsedSkill[]
  suggested_skills?: unknown[]
  unknown_terms?: string[]
  review_threshold?: number
  contact?: unknown
  entities?: Record<string, number>
}

/** What `GET /resumes/versions/{id}` returns — a summary plus the parse output. */
export interface ResumeVersionDetail extends ResumeVersionSummary {
  raw_text: string | null
  parsed_sections: ParsedSections | null
  parsed_entities: ParsedEntities | null
}

/**
 * Statuses that mean the pipeline has not finished.
 *
 * Mirrors `_IN_FLIGHT` in backend/app/api/v1/resumes.py. Lives here rather than
 * in a page because two pages need it now, and two copies of a status list
 * drift.
 */
export const IN_FLIGHT: ProcessingStatus[] = ['PENDING', 'EXTRACTING', 'PARSING', 'EMBEDDING']

export interface ResumeDetail extends Resume {
  versions: ResumeVersionSummary[]
}

export interface ResumeUploadResponse {
  resume_id: string
  version_id: string
  status: ProcessingStatus
  is_duplicate: boolean
  poll_url: string
}

export interface ProcessingStatusResponse {
  version_id: string
  status: ProcessingStatus
  percent: number
  stage_label: string
  error: string | null
  is_terminal: boolean
}

export interface Skill {
  id: string
  name: string
  category: string | null
}

/**
 * A skill the resume demonstrates but never names.
 *
 * Deliberately a different type from CandidateSkill. This is the system's
 * interpretation of what someone wrote, not a claim they made — so it is never
 * on the profile until confirmed, and always travels with its evidence.
 */
export interface SuggestedSkill {
  skill_id: string | null
  name: string
  confidence: string
  evidence: string
  section: string
}

export interface SuggestionsResponse {
  version_id: string
  suggestions: SuggestedSkill[]
  unknown_terms: string[]
}

export interface CandidateSkill {
  id: string
  skill: Skill
  proficiency: ProficiencyLevel | null
  years_of_experience: string | null
  extraction_confidence: string | null
  is_user_verified: boolean
  last_used_year: number | null
  created_at: string
}

/** Mirrors MAX_UPLOAD_BYTES in backend/app/services/file_validation.py. */
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024

export const ACCEPTED_MIME_TYPES = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
] as const

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
