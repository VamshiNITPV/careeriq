import { Link, useLocation } from 'react-router-dom'
import { JobSaveControls, UnsaveConfirmation } from '@/components/JobSaveControls'
import { useJobApplication } from '@/hooks/useJobApplication'
import type { ApplicationRead } from '@/types/application'
import {
  formatExperience,
  formatSalary,
  humanise,
  type JobDetailLocationState,
  type JobSummary,
} from '@/types/job'
import { formatPostedAge } from '@/utils/datetime'

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

export function JobCard({
  job,
  onApplicationChange,
  footer,
}: {
  job: JobSummary
  /** Lets the list swap this row's application in place, with no refetch — so
   *  scroll position, page and filters all survive a tap on the bookmark. */
  onApplicationChange?: (application: ApplicationRead | null) => void
  /** Extra line under the card, for a list that has something to add — the
   *  recommendations page puts the match score here. A slot rather than a
   *  wrapper because this component *is* the `<li>`, so a caller that wrapped
   *  it to append anything would nest one list item inside another. */
  footer?: React.ReactNode
}) {
  const salary = formatSalary(job)
  const experience = formatExperience(job)
  const state = useJobApplication(job.id, job.application, onApplicationChange)
  const location = useLocation()

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
            /*
              Where this card was rendered, filters and page and all, so the
              detail page's back link returns to the list rather than to its
              unfiltered first page.

              Derived here rather than passed as a prop: a prop is one a new
              call site can forget, and this is correct wherever the card is
              mounted. `satisfies` earns its keep because `state` is typed
              `any` by React Router, so nothing else checks the shape.
            */
            state={
              {
                backTo: `${location.pathname}${location.search}`,
              } satisfies JobDetailLocationState
            }
            className="after:absolute after:inset-0 hover:underline focus:outline-none"
          >
            {job.title}
          </Link>
        </h3>
        {/*
          `relative z-10`, and both halves are load-bearing. The title link's
          `after:absolute after:inset-0` above stretches a pseudo-element across
          the whole card and carries no z-index of its own. `z-10` alone does
          nothing, because z-index only applies to positioned elements, and
          `relative` alone happens to work today only because this comes later
          in DOM order — together they survive someone reordering the header.

          Without it the bookmark is unclickable: the tap lands on the stretched
          link and navigates to the job instead of saving it. jsdom has no
          layout, so no test in this repo can catch that.
        */}
        <div className="relative z-10 flex shrink-0 items-center gap-2">
          {salary !== null && <span className="text-sm font-medium text-slate-900">{salary}</span>}
          <JobSaveControls state={state} jobTitle={job.title} variant="icon" />
          <UnsaveConfirmation state={state} />
        </div>
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

      {/*
        Stated plainly rather than dressed as a tag, and shown even when the
        posting carries no date. Over half of them do not, and a card that
        simply says nothing there reads as "posted recently" — a claim the
        employer never made.
      */}
      <p className="mt-2 text-xs text-slate-500">{formatPostedAge(job.posted_at)}</p>

      {footer}
    </li>
  )
}
