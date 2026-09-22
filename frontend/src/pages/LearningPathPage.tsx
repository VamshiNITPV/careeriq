import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { buttonClass } from '@/components/ui/buttonStyles'
import { Spinner } from '@/components/ui/Spinner'
import { learningService } from '@/services/learningService'
import type { LearningPathResponse, LearningStep } from '@/types/learning'
import { cn } from '@/utils/cn'
import { cardClass } from '@/components/ui/cardStyles'
import { PageHeader } from '@/components/ui/PageHeader'

/**
 * What to learn, in the order to learn it (US-5.2).
 *
 * The gaps page says what is missing. This says where to start, which is a
 * different question — the most urgent gap is often not the one to begin with,
 * because it rests on something the reader also lacks.
 *
 * **Finished steps stay on the page, ticked.** The list is a route someone is
 * walking, and hiding the parts they have done would remove the only evidence of
 * progress they have.
 */

function StepRow({
  step,
  onToggle,
  busy,
}: {
  step: LearningStep
  onToggle: (next: boolean) => void
  busy: boolean
}) {
  return (
    <li className="flex gap-3 py-4 first:pt-0 last:pb-0">
      <label className="flex cursor-pointer items-start pt-0.5">
        {/* The label wraps the box, so the whole target is tappable rather than
            the 16px input alone. */}
        <input
          type="checkbox"
          checked={step.completed}
          disabled={busy}
          onChange={(event) => onToggle(event.target.checked)}
          aria-label={`Mark ${step.name} as done`}
          className="size-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600"
        />
      </label>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span
            className={cn(
              'text-sm font-medium break-words',
              // Struck through rather than removed: the reader wants to see what
              // they have finished, not have it disappear.
              step.completed ? 'text-slate-400 line-through' : 'text-slate-900',
            )}
          >
            {step.position}. {step.name}
          </span>
          <span className="shrink-0 text-xs text-slate-500 tabular-nums">
            ~{step.estimated_hours}h
          </span>
          {step.after.length > 0 && (
            /* Says *why* this one waits, so the order is arguable rather than
               arbitrary. */
            <span className="shrink-0 text-xs text-slate-400">after {step.after.join(', ')}</span>
          )}
        </div>
        <p className={cn('mt-1 text-sm', step.completed ? 'text-slate-400' : 'text-slate-600')}>
          {step.outcome}
        </p>
      </div>
    </li>
  )
}

export function LearningPathPage() {
  const [result, setResult] = useState<LearningPathResponse | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  // Which step is mid-request. One at a time is enough: the rows are separate
  // decisions and nothing here batches them.
  const [busySkill, setBusySkill] = useState<string | null>(null)

  const load = useCallback(() => {
    setState('loading')
    learningService.path().then(
      (response) => {
        setResult(response)
        setState('ready')
      },
      () => setState('error'),
    )
  }, [])

  useEffect(load, [load])

  function toggle(step: LearningStep, next: boolean) {
    setBusySkill(step.skill_id)
    // Optimistic, like the bookmark: a spinner on a checkbox for a 200ms round
    // trip reads as broken. The write is idempotent, so guessing wrong costs one
    // restored tick.
    setResult((current) =>
      current === null
        ? current
        : {
            ...current,
            steps: current.steps.map((row) =>
              row.skill_id === step.skill_id ? { ...row, completed: next } : row,
            ),
          },
    )

    learningService.setCompleted(step.skill_id, next).then(
      () => {
        setBusySkill(null)
        // Reloaded because a tick changes the plan itself, not just this row:
        // finishing a prerequisite unblocks what follows and moves the ordering.
        load()
      },
      () => {
        setBusySkill(null)
        // Put it back. Showing a step ticked that the server never recorded is
        // worse than showing nothing happened.
        setResult((current) =>
          current === null
            ? current
            : {
                ...current,
                steps: current.steps.map((row) =>
                  row.skill_id === step.skill_id ? { ...row, completed: !next } : row,
                ),
              },
        )
      },
    )
  }

  const done = result?.steps.filter((step) => step.completed).length ?? 0

  return (
    <div className="space-y-6">
      <header>
        <PageHeader
          title="Learning path"
          description={
            <>Your gaps, ordered so that nothing asks for something you have not learnt yet.</>
          }
        />
      </header>

      {state === 'loading' ? (
        <div className="flex justify-center py-12">
          <Spinner className="size-6 text-indigo-600" label="Building your learning path" />
        </div>
      ) : state === 'error' ? (
        <div className="space-y-3">
          <Alert tone="error">
            We couldn&apos;t build your learning path. This is a problem on our side, not a sign
            that there is nothing to learn.
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
            The plan is built from real postings for those roles, so we need to know what to aim at.
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
          <p className="mt-1 text-sm text-slate-600">
            We match on job titles, so a different wording may find more.
          </p>
          <Link to="/skill-gaps" className={buttonClass({ className: 'mt-4' })}>
            Back to skill gaps
          </Link>
        </section>
      ) : result.steps.length === 0 ? (
        <section className={cardClass()}>
          <p className="text-sm text-slate-600">
            Nothing to plan yet — no missing skill has guidance written for it.
          </p>
        </section>
      ) : (
        <>
          <section className={cardClass()}>
            <p className="text-sm text-slate-700" role="status">
              <strong className="text-slate-900">{result.remaining_hours}</strong> of{' '}
              {result.total_hours} hours remaining · {done} of {result.steps.length} done
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {/* Named an estimate, because it is one. There is no dataset of how
                  long people take; the numbers are ordered sensibly against each
                  other and claim nothing more. */}
              Hours are rough estimates, useful for sequencing rather than scheduling.
              {result.skipped_uncurated > 0 && (
                <>
                  {' '}
                  {result.skipped_uncurated} other missing{' '}
                  {result.skipped_uncurated === 1 ? 'skill has' : 'skills have'} no guidance written
                  yet and {result.skipped_uncurated === 1 ? 'is' : 'are'} not in this plan.
                </>
              )}
            </p>
          </section>

          <section className={cardClass()}>
            <ul className="divide-y divide-slate-200">
              {result.steps.map((step) => (
                <StepRow
                  key={step.skill_id}
                  step={step}
                  busy={busySkill === step.skill_id}
                  onToggle={(next) => toggle(step, next)}
                />
              ))}
            </ul>
          </section>

          <p className="text-xs text-slate-500">
            Ticking a step records that you studied it. It does not add the skill to your profile —
            that is your claim to make, on the{' '}
            <Link to="/resume" className="underline">
              resume page
            </Link>
            .
          </p>
        </>
      )}
    </div>
  )
}
