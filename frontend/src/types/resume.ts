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
  current_version_id: string | null
  created_at: string
  updated_at: string
}

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
