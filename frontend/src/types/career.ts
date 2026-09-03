/** Career entity types mirroring backend/app/schemas/career.py. */

import type { EmploymentType, WorkMode } from '@/types/profile'
import type { EducationLevel } from '@/types/job'

export interface CareerEntityBase {
  id: string
  /** Which upload produced this, or null when the user typed it in. */
  source_version_id: string | null
  extraction_confidence: string | null
  is_user_verified: boolean
  created_at: string
  updated_at: string
}

export interface WorkExperience extends CareerEntityBase {
  title: string
  company_name: string | null
  location: string | null
  employment_type: EmploymentType | null
  work_mode: WorkMode | null
  description: string | null
  highlights: string[]
  start_date: string | null
  end_date: string | null
  is_current: boolean
}

export interface EducationRecord extends CareerEntityBase {
  institution: string
  degree: string | null
  field_of_study: string | null
  education_level: EducationLevel | null
  grade: string | null
  start_date: string | null
  end_date: string | null
  is_current: boolean
}

export interface ProjectRecord extends CareerEntityBase {
  name: string
  description: string | null
  url: string | null
  repository_url: string | null
  highlights: string[]
  start_date: string | null
  end_date: string | null
  is_current: boolean
}

export interface CertificationRecord extends CareerEntityBase {
  name: string
  issuer: string | null
  credential_id: string | null
  credential_url: string | null
  issued_date: string | null
  expires_date: string | null
}

export interface CareerSummary {
  experiences: WorkExperience[]
  education: EducationRecord[]
  projects: ProjectRecord[]
  certifications: CertificationRecord[]
}

export type CareerKind = 'experience' | 'education' | 'projects' | 'certifications'

/**
 * Dates are month precision, and the interface must not pretend otherwise.
 *
 * The API stores "2020-01-01" because the column is a DATE, but the day is an
 * artefact — the resume said "Jan 2020". `<input type="month">` is the control
 * that matches, so these convert between the two forms.
 */
export function toMonthInput(value: string | null): string {
  return value === null ? '' : value.slice(0, 7)
}

export function fromMonthInput(value: string): string | null {
  return value === '' ? null : `${value}-01`
}

/** "Jan 2020", never "1 Jan 2020" — the day was never known. */
export function formatMonth(value: string | null): string | null {
  if (value === null) return null
  const [year, month] = value.split('-')
  if (year === undefined || month === undefined) return value
  const date = new Date(Number(year), Number(month) - 1, 1)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })
}

export function formatSpan(entity: {
  start_date: string | null
  end_date: string | null
  is_current: boolean
}): string | null {
  const start = formatMonth(entity.start_date)
  const end = entity.is_current ? 'Present' : formatMonth(entity.end_date)
  if (start === null && end === null) return null
  if (start === null) return end
  if (end === null) return start
  return `${start} – ${end}`
}
