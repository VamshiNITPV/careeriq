import { useCallback, useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { ApiError } from '@/services/apiClient'
import { jobService } from '@/services/jobService'
import {
  educationLabel,
  formatExperience,
  formatSalary,
  humanise,
  type JobDetail,
  type JobSkillRead,
} from '@/types/job'
import { cn } from '@/utils/cn'

/** One labelled fact. Rendered only when the posting actually stated it. */
function Fact({ label, value }: { label: string; value: string | null }) {
  if (value === null) return null
  return (
    <div>
      <dt className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-900">{value}</dd>
    </div>
  )
}

function SkillPill({ skill }: { skill: JobSkillRead }) {
  const required = skill.requirement === 'REQUIRED'
  const years = skill.min_years !== null ? ` · ${Number(skill.min_years)}+ yrs` : ''
  return (
    <span
      className={cn(
        'rounded-full border px-3 py-1 text-sm',
        required
          ? 'border-indigo-600 bg-indigo-50 text-indigo-700'
          : 'border-slate-300 text-slate-600',
      )}
    >
      {skill.name}
      {years}
    </span>
  )
}

function BulletList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <section>
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  )
}

export function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const location = useLocation()
  // Set by AddJobPage when the submission matched a posting already in the
  // corpus. Read once — a reload should not keep announcing it.
  const [isDuplicate] = useState(
    () => (location.state as { isDuplicate?: boolean } | null)?.isDuplicate === true,
  )

  const [job, setJob] = useState<JobDetail | null>(null)
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    if (jobId === undefined) return
    setLoadState('loading')
    setError(null)
    jobService.get(jobId).then(
      (result) => {
        setJob(result)
        setLoadState('ready')
      },
      (caught: unknown) => {
        setError(
          caught instanceof ApiError && caught.status === 404
            ? 'That job no longer exists.'
            : 'Could not load this job. Please try again.',
        )
        setLoadState('error')
      },
    )
  }, [jobId])

  useEffect(load, [load])

  if (loadState === 'loading') {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="size-8 text-indigo-600" label="Loading this job" />
      </div>
    )
  }

  if (loadState === 'error' || job === null) {
    return (
      <div className="space-y-4">
        <Alert tone="error" title="We couldn't load this job">
          {error ?? 'Please try again.'}
        </Alert>
        <div className="flex gap-3">
          <Button variant="secondary" size="sm" onClick={load}>
            Try again
          </Button>
          <Link to="/jobs" className="self-center text-sm text-indigo-600 hover:underline">
            Back to jobs
          </Link>
        </div>
      </div>
    )
  }

  const required = job.skills.filter((s) => s.requirement === 'REQUIRED')
  const preferred = job.skills.filter((s) => s.requirement === 'PREFERRED')

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Link to="/jobs" className="text-sm font-medium text-indigo-600 hover:underline">
        ← Back to jobs
      </Link>

      {isDuplicate && (
        <Alert tone="info">
          This posting was already here, so we showed you the one we had rather than adding a
          second copy.
        </Alert>
      )}

      <header className="rounded-xl border border-slate-200 bg-white p-6">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">{job.title}</h1>
        <p className="mt-1 text-sm text-slate-600">
          {job.company?.name ?? 'Company not stated'}
          {job.location !== null && <span className="text-slate-400"> · {job.location}</span>}
        </p>

        <dl className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          <Fact label="Pay" value={formatSalary(job)} />
          <Fact label="Experience" value={formatExperience(job)} />
          <Fact label="Level" value={job.experience_level && humanise(job.experience_level)} />
          <Fact label="Work mode" value={job.work_mode && humanise(job.work_mode)} />
          <Fact label="Type" value={job.employment_type && humanise(job.employment_type)} />
          <Fact
            label="Education"
            value={job.min_education !== null ? educationLabel(job.min_education) : null}
          />
        </dl>

        {job.source_url !== null && (
          <a
            href={job.source_url}
            target="_blank"
            // noreferrer as well as noopener: without it the opened page can
            // read where it was linked from.
            rel="noopener noreferrer"
            className="mt-5 inline-block text-sm font-medium text-indigo-600 hover:underline"
          >
            View the original posting ↗
          </a>
        )}
      </header>

      {job.skills.length > 0 && (
        <section className="rounded-xl border border-slate-200 bg-white p-6">
          <h2 className="text-base font-semibold text-slate-900">Skills this job asks for</h2>
          <p className="mt-1 text-sm text-slate-600">
            {/* The distinction is stated because it is what drives matching, and
                because a reader deserves to know which of these is a hard gate. */}
            Read from the posting. Required skills weigh more than preferred ones when this job is
            matched against your profile.
          </p>

          {required.length > 0 && (
            <div className="mt-4">
              <h3 className="text-sm font-medium text-slate-900">Required</h3>
              <div className="mt-2 flex flex-wrap gap-2">
                {required.map((skill) => (
                  <SkillPill key={skill.skill_id} skill={skill} />
                ))}
              </div>
            </div>
          )}

          {preferred.length > 0 && (
            <div className="mt-4">
              <h3 className="text-sm font-medium text-slate-900">Preferred</h3>
              <div className="mt-2 flex flex-wrap gap-2">
                {preferred.map((skill) => (
                  <SkillPill key={skill.skill_id} skill={skill} />
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      <div className="space-y-6 rounded-xl border border-slate-200 bg-white p-6">
        <BulletList title="Responsibilities" items={job.responsibilities} />
        <BulletList title="Requirements" items={job.requirements} />
        <BulletList title="Benefits" items={job.benefits} />

        <details className="group">
          <summary className="cursor-pointer text-sm font-medium text-indigo-600 hover:underline">
            Show the original description
          </summary>
          {/* The posting as pasted, never reformatted. Everything above is
              derived from it, so this is what to check when the parse looks
              wrong. */}
          <pre className="mt-3 max-h-96 overflow-auto rounded-lg bg-slate-50 p-4 text-sm whitespace-pre-wrap text-slate-700">
            {job.description_raw}
          </pre>
        </details>
      </div>
    </div>
  )
}
