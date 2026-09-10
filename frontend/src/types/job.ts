/** Job types mirroring backend/app/schemas/job.py. */

import type { ApplicationRead } from '@/types/application'
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
export type JobSource = 'USER_SUBMITTED' | 'DATASET_IMPORT' | 'PARTNER_API'
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
  /**
   * What *you* have done about this job, or null.
   *
   * Per-caller, on a row from a shared corpus — which is fine here because both
   * job endpoints already require a caller and nothing is cached. A nullable
   * object rather than `is_saved`/`is_applied` booleans: it reads as a separate
   * entity of yours rather than a property of the job, it carries `applied_at`
   * which the remove-confirmation needs, and it is the same shape the PUT
   * returns, so updating a row is a field swap with no translation.
   */
  application: ApplicationRead | null
  /**
   * Your match score out of 100, when the list was sorted by match.
   *
   * Null everywhere else — and null is not zero. A browse-sorted list has not
   * computed a score, which is a different statement from "this job scores
   * nothing for you". Render the row without a score rather than a 0.
   *
   * A string, like every score in this API, so 68.4 cannot arrive as
   * 68.40000000000001.
   */
  match_score: string | null
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
  /**
   * Rows in the whole list.
   *
   * Under `sort=match` this is **capped by the recall limit (200)**, so it is the
   * number of ranked matches rather than a corpus count. The page's wording has
   * to reflect that: "247 matches" would be an invented number.
   */
  total: number
  limit: number
  offset: number
  /**
   * Why `items` may be empty under `sort=match`.
   *
   * Always READY for a date-sorted browse, which cannot fail these ways. The two
   * other values are not errors: NO_RESUME means there is nothing to match
   * against, PENDING means the resume is not embedded yet. Both arrive as 200s
   * with data, because an empty list with no explanation reads as "no job in the
   * world suits you" — a much more discouraging claim than either true one.
   */
  availability: 'READY' | 'PENDING' | 'NO_RESUME'
  /** Which ranking produced the scores, or null in browse mode. */
  ranking_version: string | null
}

export interface JobSubmitResponse {
  job: JobDetail
  is_duplicate: boolean
}

/**
 * Link state that JobDetailPage understands.
 *
 * Two independent senders — JobCard, which knows which list you were looking
 * at, and AddJobPage, which knows the posting was already in the corpus. Both
 * fields are optional and read independently, so a third sender adds a field
 * rather than colliding with the other two.
 */
export interface JobDetailLocationState {
  /** Path and search of the list to return to, e.g. "/jobs?q=python&offset=20". */
  backTo?: string
  isDuplicate?: boolean
}

export interface SimilarJob {
  job: JobSummary
  /**
   * Raw cosine in [0, 1], for debugging and evaluation — **never rendered**.
   * Raw cosine on this model needs rescaling before it means anything (ml.md
   * §4.1), and that rescaling belongs to the scoring step. A bare 0.71 on a
   * card would look like a percentage and would not be one.
   */
  similarity: number
}

export interface SimilarJobsResponse {
  items: SimilarJob[]
  /**
   * Why `items` is empty, because it has three different reasons:
   *   READY    the comparison ran and nothing was close enough
   *   PENDING  this posting has no vector yet
   *   DISABLED embeddings are switched off entirely (the default)
   */
  availability: 'READY' | 'PENDING' | 'DISABLED'
  limit: number
  model_name: string | null
  model_version: string | null
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
  /**
   * Show postings published within this many days. Undated postings are
   * included — over half the corpus has no stated date, and a missing date says
   * nothing about age.
   */
  posted_within_days?: number
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

/**
 * Preset windows for the "Posted within" filter. `value` is the day count sent
 * as `posted_within_days`.
 *
 * Deliberately coarse. The provider reports whole days and often no date at
 * all, so offering "last 24 hours" would imply a resolution the data has not
 * got. Thirty days is the widest because a posting older than that is rarely
 * still open, and the default — no window — already shows everything.
 */
export const POSTED_WITHIN_OPTIONS = [
  { value: '7', label: 'Last 7 days' },
  { value: '14', label: 'Last 14 days' },
  { value: '30', label: 'Last 30 days' },
]

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

// ---------------------------------------------------------------- match score

/** The six dimensions of the ranking formula, in documented weight order. */
export type MatchDimensionName =
  | 'semantic'
  | 'skill'
  | 'experience'
  | 'education'
  | 'location'
  | 'salary'

/**
 * Why a dimension scored what it did.
 *
 * The distinction that matters to the interface is the last two. Both score a
 * neutral 0.5, but `NEEDS_PROFILE` is something the user can fix and
 * `NEEDS_DATA` is not — showing "complete your profile" because an employer
 * left a field blank would be blaming the reader for someone else's omission.
 */
export type MatchDimensionStatus = 'SCORED' | 'NOT_STATED' | 'NEEDS_PROFILE' | 'NEEDS_DATA'

export interface MatchDimension {
  dimension: MatchDimensionName
  /** [0, 1]. Decimal over the wire, so a string. */
  score: string
  weight: string
  /** `score × weight × 100`, to one place. The six sum to `overall_score`. */
  contribution: string
  status: MatchDimensionStatus
  reason: string
}

export interface MatchedSkill {
  id: string
  name: string
  requirement: 'REQUIRED' | 'PREFERRED'
}

export interface MatchResponse {
  job_id: string
  /**
   *   READY      all six dimensions ran
   *   PARTIAL    the semantic dimension could not run — no provider, or a
   *              vector that is not built yet. The breakdown still sums
   *   NO_RESUME  nothing uploaded, so there is no score at all
   */
  availability: 'READY' | 'PARTIAL' | 'NO_RESUME'
  overall_score: string | null
  breakdown: MatchDimension[]
  /** Weight of the rows that measured something — the honesty disclosure. */
  scored_weight: string
  skills: {
    matched: MatchedSkill[]
    partial: MatchedSkill[]
    missing: MatchedSkill[]
  }
  ranking_version: string | null
  resume_version_id: string | null
  computed_at: string | null
}

// ------------------------------------------------------------ recommendations

export interface RecommendedJob {
  job: JobSummary
  /** 0–100, one decimal place. Decimal over the wire, so a string. */
  score: string
  breakdown: MatchDimension[]
  scored_weight: string
  skills: {
    matched: MatchedSkill[]
    partial: MatchedSkill[]
    missing: MatchedSkill[]
  }
}

export interface RecommendationsResponse {
  items: RecommendedJob[]
  /**
   *   READY      the ranking ran
   *   PENDING    the resume has no vector yet — the indexer has not reached it
   *   NO_RESUME  nothing uploaded, so there is nothing to rank against
   */
  availability: 'READY' | 'PENDING' | 'NO_RESUME'
  /** Opaque. Null on the last page — never parse it. */
  next_cursor: string | null
  limit: number
  /**
   * How many of the recalled set survived the filters. Deliberately not a
   * corpus-wide total: two-stage retrieval never looks at the whole corpus, so
   * any "total" would be a number about the recall set dressed as a number
   * about the market.
   */
  considered: number
  ranking_version: string | null
  resume_version_id: string | null
  computed_at: string | null
}
