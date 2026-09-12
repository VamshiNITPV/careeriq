import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { buttonClass } from '@/components/ui/buttonStyles'
import { Spinner } from '@/components/ui/Spinner'
import { skillGapService } from '@/services/skillGapService'
import type { GapSeverity, GapStatus, SkillGapsResponse } from '@/types/skillGap'
import { cn } from '@/utils/cn'

/**
 * What stands between you and the roles you are aiming at (US-5.1).
 *
 * The first screen in this product that gives advice rather than a number. A
 * match score says a job is a 68; this says which skills the jobs you want ask
 * for, which of those you already have, and what to learn next.
 *
 * **The denominator is on the page, not buried.** "Across 68 matching jobs" is
 * part of the claim: the same list computed from four postings would mean far
 * less, and a reader who cannot see how many jobs it came from has no way to
 * judge how much to trust it.
 */

/** Full literal class strings — Tailwind v4 scans source text and emits nothing
 *  for a computed name, so `bg-${tone}-50` would simply not render. */
const SEVERITY_STYLE: Record<GapSeverity, string> = {
  CRITICAL: 'bg-red-50 text-red-700 ring-red-600/20',
  HIGH: 'bg-orange-50 text-orange-700 ring-orange-600/20',
  MEDIUM: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  LOW: 'bg-slate-100 text-slate-600 ring-slate-500/20',
}

const STATUS_STYLE: Record<GapStatus, string> = {
  MISSING: 'bg-red-50 text-red-700 ring-red-600/20',
  PARTIAL: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  STRONG: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
}

const STATUS_LABEL: Record<GapStatus, string> = {
  MISSING: 'Missing',
  PARTIAL: 'Related',
  STRONG: 'You have this',
}

function Pill({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
        className,
      )}
    >
      {children}
    </span>
  )
}

function GapRow({ gap }: { gap: SkillGapsResponse['items'][number] }) {
  // Rounded for reading, not for precision. "54% of the jobs you want" is the
  // claim; two decimal places would imply a certainty 68 postings cannot carry.
  const share = Math.round(Number(gap.frequency) * 100)

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3 first:pt-0 last:pb-0">
      <span className="min-w-48 flex-1 text-sm font-medium break-words text-slate-900">
        {gap.name}
      </span>
      <Pill className={STATUS_STYLE[gap.status]}>{STATUS_LABEL[gap.status]}</Pill>
      {/* Severity is only meaningful for something you lack. Showing "CRITICAL"
          beside a skill the reader already has would read as an alarm about
          nothing. */}
      {gap.status !== 'STRONG' && (
        <Pill className={SEVERITY_STYLE[gap.severity]}>{gap.severity.toLowerCase()}</Pill>
      )}
      <span className="shrink-0 text-xs text-slate-500 tabular-nums">
        {share}% of target jobs · {gap.job_count}
      </span>
    </li>
  )
}

export function SkillGapsPage() {
  const [result, setResult] = useState<SkillGapsResponse | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')

  const load = useCallback(() => {
    setState('loading')
    skillGapService.gaps().then(
      (response) => {
        setResult(response)
        setState('ready')
      },
      () => setState('error'),
    )
  }, [])

  useEffect(load, [load])

  const missing = result?.items.filter((gap) => gap.status === 'MISSING') ?? []
  const covered = result?.items.filter((gap) => gap.status !== 'MISSING') ?? []

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Skill gaps</h1>
        <p className="mt-1 text-sm text-slate-600">
          What the roles you are aiming at ask for, and how much of it you already have.
        </p>
      </header>

      {state === 'loading' ? (
        <div className="flex justify-center py-12">
          <Spinner className="size-6 text-indigo-600" label="Working out your skill gaps" />
        </div>
      ) : state === 'error' ? (
        /* A page whose entire purpose failed has to say so. Showing an empty
           list would read as "you have no gaps", which is both untrue and the
           most flattering possible way to be wrong. */
        <div className="space-y-3">
          <Alert tone="error">
            We couldn&apos;t work out your skill gaps. This is a problem on our side, not a sign
            that you have none.
          </Alert>
          <Button variant="secondary" size="sm" onClick={load}>
            Try again
          </Button>
        </div>
      ) : result === null ? null : result.availability === 'NO_TARGET' ? (
        <section className="rounded-xl border border-dashed border-slate-300 bg-white p-6">
          <p className="text-sm font-medium text-slate-900">
            Tell us which roles you are aiming at.
          </p>
          <p className="mt-1 text-sm text-slate-600">
            Gaps are measured against real postings for those roles, so we need to know what to
            compare you with.
          </p>
          <Link to="/profile" className={buttonClass({ className: 'mt-4' })}>
            Set your target roles
          </Link>
        </section>
      ) : result.availability === 'NO_JOBS' ? (
        <section className="rounded-xl border border-dashed border-slate-300 bg-white p-6">
          <p className="text-sm font-medium text-slate-900">
            No live jobs match {result.target_roles.join(' or ')} yet.
          </p>
          {/* Names the roles it tried, so the reader can see whether the problem
              is their wording or an empty corpus — two different fixes. */}
          <p className="mt-1 text-sm text-slate-600">
            We match on job titles, so a different wording may find more. More postings arrive
            daily.
          </p>
          <Link to="/profile" className={buttonClass({ className: 'mt-4' })}>
            Edit your target roles
          </Link>
        </section>
      ) : result.items.length === 0 ? (
        <section className="rounded-xl border border-slate-200 bg-white p-6">
          <p className="text-sm text-slate-600">
            Nothing stands out across the {result.target_jobs} matching{' '}
            {result.target_jobs === 1 ? 'job' : 'jobs'} we found.
          </p>
        </section>
      ) : (
        <>
          <p className="text-sm text-slate-600" role="status">
            Measured across <strong className="text-slate-900">{result.target_jobs}</strong> live{' '}
            {result.target_jobs === 1 ? 'job' : 'jobs'} matching{' '}
            {result.target_roles.join(', ')}.
          </p>

          {missing.length > 0 && (
            <section className="rounded-xl border border-slate-200 bg-white p-4 sm:p-6">
              <h2 className="text-base font-semibold text-slate-900">Learn these next</h2>
              <p className="mt-1 text-sm text-slate-600">
                Ordered by how many of your target jobs ask for them.
              </p>
              <ul className="mt-4 divide-y divide-slate-200">
                {missing.map((gap) => (
                  <GapRow key={gap.skill_id} gap={gap} />
                ))}
              </ul>
            </section>
          )}

          {covered.length > 0 && (
            <section className="rounded-xl border border-slate-200 bg-white p-4 sm:p-6">
              <h2 className="text-base font-semibold text-slate-900">Already covered</h2>
              <p className="mt-1 text-sm text-slate-600">
                Skills your target roles ask for that are on your profile. &ldquo;Related&rdquo;
                means you have something adjacent rather than the skill itself.
              </p>
              <ul className="mt-4 divide-y divide-slate-200">
                {covered.map((gap) => (
                  <GapRow key={gap.skill_id} gap={gap} />
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  )
}
