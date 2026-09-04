/** Job types mirroring backend/app/schemas/job.py. */

import type { EmploymentType, WorkMode } from '@/types/profile'

export type ExperienceLevel =
  | 'INTERN'
  | 'ENTRY'
  | 'JUNIOR'
  | 'MID'
  | 'SENIOR'
  | 'LEAD'
  | 'PRINCIPAL'

export type EducationLevel =
  | 'NONE'
  | 'HIGH_SCHOOL'
  | 'DIPLOMA'
  | 'BACHELORS'
  | 'MASTERS'
  | 'DOCTORATE'

export type SalaryPeriod = 'YEARLY' | 'MONTHLY' | 'HOURLY'
export type SkillRequirement = 'REQUIRED' | 'PREFERRED'
export type JobSource = 'USER_SUBMITTED' | 'DATASET_IMPORT'
export type JobStatus = 'ACTIVE' | 'DUPLICATE'

export interface CompanyRead {
  id: string
  name: string
  website: string | null
  industry: string | null
}

export interface JobSkillRead {
  skill_id: string
  name: string
  requirement: SkillRequirement
  /** Numerics arrive as strings so no precision is lost in transit. */
  min_years: string | null
  extraction_confidence: string | null
}

export interface JobSummary {
  id: string
  title: string
  company: CompanyRead | null
  location: string | null
  country_code: string | null
  work_mode: WorkMode | null
  employment_type: EmploymentType | null
  experience_level: ExperienceLevel | null
  min_years_experience: string | null
  max_years_experience: string | null
  salary_min: string | null
  salary_max: string | null
  salary_currency: string | null
  salary_period: SalaryPeriod | null
  posted_at: string | null
  created_at: string
  skill_count: number
}

export interface JobDetail extends JobSummary {
  source: JobSource
  source_url: string | null
  status: JobStatus
  description_raw: string
  responsibilities: string[]
  requirements: string[]
  benefits: string[]
  min_education: EducationLevel | null
  expires_at: string | null
  skills: JobSkillRead[]
}

export interface JobListResponse {
  items: JobSummary[]
  total: number
  limit: number
  offset: number
}

export interface JobSubmitResponse {
  job: JobDetail
  is_duplicate: boolean
}

export interface JobFilters {
  q?: string
  work_mode?: WorkMode
  employment_type?: EmploymentType
  /**
   * Still a supported API filter, though the browse UI now filters on years —
   * the ranking formula is numeric and the seniority enum plays no part in it.
   */
  experience_level?: ExperienceLevel
  /** Show jobs whose stated range covers this many years. */
  years_experience?: number
  country_code?: string
  limit?: number
  offset?: number
}

/** Mirrors MAX_DESCRIPTION_CHARS in backend/app/schemas/job.py. */
export const MAX_DESCRIPTION_CHARS = 60_000
/** Mirrors MIN_DESCRIPTION_CHARS in backend/app/services/job/pipeline.py. */
export const MIN_DESCRIPTION_CHARS = 200

/**
 * Preset choices for the browse filter. `value` is the number sent as
 * `years_experience`; a job matches when its stated range covers it.
 *
 * Generated rather than written out: eleven near-identical entries invite a
 * typo, and the only irregularity is the singular at 1.
 *
 * No `keywords` needed — comboboxCore's normalizeText folds "5+ years" to
 * "5 years", so typing 5 is already a prefix match, and typing 1 correctly
 * offers both "1+ year" and "10+ years".
 */
export const EXPERIENCE_YEAR_OPTIONS = Array.from({ length: 11 }, (_, years) => ({
  value: String(years),
  label: years === 1 ? '1+ year' : `${years}+ years`,
}))

const EDUCATION_LABELS: Record<EducationLevel, string> = {
  NONE: 'No formal requirement',
  HIGH_SCHOOL: 'High school',
  DIPLOMA: 'Diploma',
  BACHELORS: "Bachelor's degree",
  MASTERS: "Master's degree",
  DOCTORATE: 'Doctorate',
}

export function educationLabel(level: EducationLevel): string {
  return EDUCATION_LABELS[level]
}

/** "Full time" from "FULL_TIME" — for enums with no curated label list. */
export function humanise(value: string): string {
  return value.charAt(0) + value.slice(1).toLowerCase().replace(/_/g, ' ')
}

const PERIOD_SUFFIX: Record<SalaryPeriod, string> = {
  YEARLY: '/yr',
  MONTHLY: '/mo',
  HOURLY: '/hr',
}

/**
 * Render a pay range the way the posting stated it.
 *
 * Deliberately does not convert currencies or normalise periods. The backend
 * stores what the posting said, and inventing a converted figure would put a
 * number in front of the user that no employer ever wrote.
 */
export function formatSalary(job: {
  salary_min: string | null
  salary_max: string | null
  salary_currency: string | null
  salary_period: SalaryPeriod | null
}): string | null {
  if (job.salary_min === null && job.salary_max === null) return null

  const currency = job.salary_currency ?? ''
  const format = (value: string) => {
    const amount = Number(value)
    if (!Number.isFinite(amount)) return value
    // Compact notation: a range of 2,800,000–4,500,000 is unreadable at a
    // glance, and "2.8M" is what the eye is actually looking for in a list.
    return new Intl.NumberFormat(undefined, {
      notation: amount >= 100_000 ? 'compact' : 'standard',
      maximumFractionDigits: 1,
    }).format(amount)
  }

  const range =
    job.salary_min !== null && job.salary_max !== null
      ? `${format(job.salary_min)} – ${format(job.salary_max)}`
      : format((job.salary_min ?? job.salary_max)!)

  const suffix = job.salary_period !== null ? PERIOD_SUFFIX[job.salary_period] : ''
  return `${currency} ${range}${suffix}`.trim()
}

/** "4–7 years", "5+ years", or null when the posting did not say. */
export function formatExperience(job: {
  min_years_experience: string | null
  max_years_experience: string | null
}): string | null {
  const min = job.min_years_experience
  const max = job.max_years_experience
  if (min === null && max === null) return null

  const n = (value: string) => Number(value).toString()
  if (min !== null && max !== null) return `${n(min)}–${n(max)} years`
  if (min !== null) return `${n(min)}+ years`
  return `up to ${n(max!)} years`
}
