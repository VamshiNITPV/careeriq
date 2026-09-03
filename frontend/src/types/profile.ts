/** Profile types mirroring backend/app/schemas/profile.py. */

export type WorkMode = 'ONSITE' | 'HYBRID' | 'REMOTE'
export type EmploymentType =
  | 'FULL_TIME'
  | 'PART_TIME'
  | 'CONTRACT'
  | 'INTERNSHIP'
  | 'TEMPORARY'

export interface Profile {
  id: string
  user_id: string

  full_name: string | null
  headline: string | null
  location: string | null
  country_code: string | null
  phone: string | null
  summary: string | null
  linkedin_url: string | null
  github_url: string | null
  portfolio_url: string | null

  // Derived from the resume, not editable here yet.
  years_of_experience: string | null
  current_experience_level: string | null
  highest_education: string | null

  target_roles: string[]
  preferred_locations: string[]
  preferred_work_modes: WorkMode[]
  preferred_employment_types: EmploymentType[]
  // Decimal on the wire — the API sends it as a string to avoid float drift.
  min_salary_expectation: string | null
  salary_currency: string | null
  open_to_relocation: boolean
  preferences_updated_at: string | null

  created_at: string
  updated_at: string
}

/** PATCH body — only the keys present are changed. */
export type ProfilePersonalUpdate = Partial<
  Pick<
    Profile,
    | 'full_name'
    | 'headline'
    | 'location'
    | 'country_code'
    | 'phone'
    | 'summary'
    | 'linkedin_url'
    | 'github_url'
    | 'portfolio_url'
  >
>

/**
 * PUT body — replaces the whole preference set.
 *
 * Not a Partial, deliberately: the endpoint replaces wholesale, so every field
 * must be sent. Typing it as partial would let a caller drop a key and silently
 * clear it.
 */
export interface PreferencesReplace {
  target_roles: string[]
  preferred_locations: string[]
  preferred_work_modes: WorkMode[]
  preferred_employment_types: EmploymentType[]
  min_salary_expectation: string | null
  salary_currency: string | null
  open_to_relocation: boolean
}

export const WORK_MODES: { value: WorkMode; label: string }[] = [
  { value: 'REMOTE', label: 'Remote' },
  { value: 'HYBRID', label: 'Hybrid' },
  { value: 'ONSITE', label: 'On-site' },
]

export const EMPLOYMENT_TYPES: { value: EmploymentType; label: string }[] = [
  { value: 'FULL_TIME', label: 'Full-time' },
  { value: 'PART_TIME', label: 'Part-time' },
  { value: 'CONTRACT', label: 'Contract' },
  { value: 'INTERNSHIP', label: 'Internship' },
  { value: 'TEMPORARY', label: 'Temporary' },
]
