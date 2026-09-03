import { Link } from 'react-router-dom'
import { formatExperience, formatSalary, humanise, type JobSummary } from '@/types/job'

/**
 * One row in the browse list.
 *
 * Every fact shown is one the parser either found or did not — nothing is
 * inferred for display. A posting with no salary shows no salary rather than
 * "competitive", which would be the interface inventing a claim the employer
 * never made.
 */

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
      {children}
    </span>
  )
}

export function JobCard({ job }: { job: JobSummary }) {
  const salary = formatSalary(job)
  const experience = formatExperience(job)

  return (
    <li className="relative rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200 transition-shadow focus-within:ring-2 focus-within:ring-indigo-600 hover:shadow-md">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
        <h3 className="text-base font-semibold text-indigo-700">
          {/*
            Only the title is the link, but `after:absolute after:inset-0`
            stretches its hit area over the whole card. Wrapping everything in
            the anchor instead would give the link an accessible name of
            "Senior Data Engineer Zeta Payments · Bengaluru, India Hybrid Full
            time Senior 4–7 years 7 skills" — one run-on string a screen reader
            user has to sit through to know where it goes.
          */}
          <Link
            to={`/jobs/${job.id}`}
            className="after:absolute after:inset-0 hover:underline focus:outline-none"
          >
            {job.title}
          </Link>
        </h3>
        {salary !== null && (
          <span className="shrink-0 text-sm font-medium text-slate-900">{salary}</span>
        )}
      </div>

      <p className="mt-0.5 text-sm text-slate-600">
        {job.company?.name ?? 'Company not stated'}
        {job.location !== null && <span className="text-slate-400"> · {job.location}</span>}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {job.work_mode !== null && <Tag>{humanise(job.work_mode)}</Tag>}
        {job.employment_type !== null && <Tag>{humanise(job.employment_type)}</Tag>}
        {job.experience_level !== null && <Tag>{humanise(job.experience_level)}</Tag>}
        {experience !== null && <Tag>{experience}</Tag>}
        {job.skill_count > 0 && (
          <span className="text-xs text-slate-500">
            {job.skill_count} skill{job.skill_count === 1 ? '' : 's'}
          </span>
        )}
      </div>
    </li>
  )
}
