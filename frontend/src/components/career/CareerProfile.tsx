import { useCallback, useEffect, useState } from 'react'
import { CareerSection, type FieldSpec } from '@/components/career/CareerSection'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { careerService } from '@/services/careerService'
import { formatSpan, type CareerSummary } from '@/types/career'
import { EMPLOYMENT_TYPES, WORK_MODES } from '@/types/profile'

/**
 * The structured career profile a resume produces (US-2.3).
 *
 * Everything here is editable, because extraction is heuristic reading of
 * wildly variable layouts and will be wrong sometimes (US-2.4 AC1). A wrong row
 * left uneditable is permanent, and it is scored against every job the user
 * sees.
 */

const EDUCATION_LEVELS = [
  { value: 'HIGH_SCHOOL', label: 'High school' },
  { value: 'DIPLOMA', label: 'Diploma' },
  { value: 'BACHELORS', label: "Bachelor's" },
  { value: 'MASTERS', label: "Master's" },
  { value: 'DOCTORATE', label: 'Doctorate' },
] as const

const EXPERIENCE_FIELDS: readonly FieldSpec[] = [
  { key: 'title', label: 'Job title', type: 'text', required: true, half: true },
  { key: 'company_name', label: 'Company', type: 'text', half: true },
  { key: 'location', label: 'Location', type: 'text', half: true },
  { key: 'employment_type', label: 'Employment type', type: 'select', options: EMPLOYMENT_TYPES, half: true },
  { key: 'work_mode', label: 'Work mode', type: 'select', options: WORK_MODES, half: true },
  { key: 'start_date', label: 'Started', type: 'month', half: true },
  { key: 'end_date', label: 'Ended', type: 'month', hint: 'Leave blank if this is your current role', half: true },
  { key: 'is_current', label: 'I still work here', type: 'checkbox' },
  { key: 'highlights', label: 'Highlights', type: 'lines', hint: 'One per line, as they appear on your resume' },
]

const EDUCATION_FIELDS: readonly FieldSpec[] = [
  { key: 'institution', label: 'Institution', type: 'text', required: true, half: true },
  { key: 'degree', label: 'Degree', type: 'text', hint: 'As written, e.g. B.Tech', half: true },
  { key: 'field_of_study', label: 'Field of study', type: 'text', half: true },
  { key: 'education_level', label: 'Level', type: 'select', options: EDUCATION_LEVELS, half: true },
  { key: 'start_date', label: 'Started', type: 'month', half: true },
  { key: 'end_date', label: 'Finished', type: 'month', half: true },
  { key: 'grade', label: 'Grade', type: 'text', hint: 'However your transcript states it', half: true },
  { key: 'is_current', label: 'I am still studying here', type: 'checkbox' },
]

const PROJECT_FIELDS: readonly FieldSpec[] = [
  { key: 'name', label: 'Name', type: 'text', required: true, half: true },
  { key: 'url', label: 'Link', type: 'text', half: true },
  { key: 'repository_url', label: 'Repository', type: 'text', half: true },
  { key: 'start_date', label: 'Started', type: 'month', half: true },
  { key: 'end_date', label: 'Finished', type: 'month', half: true },
  { key: 'description', label: 'Description', type: 'textarea' },
  { key: 'highlights', label: 'Highlights', type: 'lines', hint: 'One per line' },
]

const CERTIFICATION_FIELDS: readonly FieldSpec[] = [
  { key: 'name', label: 'Name', type: 'text', required: true, half: true },
  { key: 'issuer', label: 'Issued by', type: 'text', half: true },
  { key: 'issued_date', label: 'Issued', type: 'month', half: true },
  { key: 'expires_date', label: 'Expires', type: 'month', hint: 'Leave blank if it does not expire', half: true },
  { key: 'credential_id', label: 'Credential ID', type: 'text', half: true },
  { key: 'credential_url', label: 'Verification link', type: 'text', half: true },
]

const EMPTY: CareerSummary = {
  experiences: [],
  education: [],
  projects: [],
  certifications: [],
}

export function CareerProfile() {
  const [summary, setSummary] = useState<CareerSummary>(EMPTY)
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading')

  const load = useCallback(() => {
    setLoadState('loading')
    careerService.summary().then(
      (result) => {
        setSummary(result)
        setLoadState('ready')
      },
      // An error state rather than an empty one: telling someone their work
      // history is empty when the request merely failed is a lie they may act
      // on by re-typing all of it.
      () => setLoadState('error'),
    )
  }, [])

  useEffect(load, [load])

  if (loadState === 'loading') {
    return (
      <div className="flex justify-center py-10">
        <Spinner className="size-6 text-indigo-600" label="Loading your career profile" />
      </div>
    )
  }

  if (loadState === 'error') {
    return (
      <div className="space-y-3">
        <Alert tone="error" title="We couldn't load your career profile">
          Please try again.
        </Alert>
        <Button variant="secondary" size="sm" onClick={load}>
          Try again
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <CareerSection
        kind="experience"
        title="Work history"
        description="Read from your resume. Correct anything we got wrong — this drives your match scores."
        noun="role"
        items={summary.experiences}
        fields={EXPERIENCE_FIELDS}
        emptyHint="Nothing yet. Upload a resume, or add a role by hand."
        onChanged={load}
        renderSummary={(item) => ({
          primary: item.title,
          secondary: item.company_name ?? null,
          meta: [formatSpan(item), item.location].filter(Boolean).join(' · ') || null,
        })}
      />

      <CareerSection
        kind="education"
        title="Education"
        description="Your qualifications, as the ranking compares them against a job's requirement."
        noun="qualification"
        items={summary.education}
        fields={EDUCATION_FIELDS}
        emptyHint="Nothing yet. Upload a resume, or add a qualification by hand."
        onChanged={load}
        renderSummary={(item) => ({
          primary: item.degree ?? item.institution,
          secondary: item.degree === null ? null : item.institution,
          meta: [formatSpan(item), item.grade].filter(Boolean).join(' · ') || null,
        })}
      />

      <CareerSection
        kind="projects"
        title="Projects"
        description="What you have built."
        noun="project"
        items={summary.projects}
        fields={PROJECT_FIELDS}
        emptyHint="Nothing yet. Upload a resume, or add a project by hand."
        onChanged={load}
        renderSummary={(item) => ({
          primary: item.name,
          secondary: item.description,
          meta: formatSpan(item),
        })}
      />

      <CareerSection
        kind="certifications"
        title="Certifications"
        description="Credentials you hold."
        noun="certification"
        items={summary.certifications}
        fields={CERTIFICATION_FIELDS}
        emptyHint="Nothing yet. Upload a resume, or add a certification by hand."
        onChanged={load}
        renderSummary={(item) => ({
          primary: item.name,
          secondary: item.issuer,
          meta: formatSpan({
            start_date: item.issued_date,
            end_date: item.expires_date,
            is_current: false,
          }),
        })}
      />

      {/* Stated once, at the bottom, rather than repeated on every section. */}
      <p className="text-sm text-slate-500">
        Anything you edit here is marked as confirmed, and is never overwritten when a resume is
        re-extracted.
      </p>
    </div>
  )
}
