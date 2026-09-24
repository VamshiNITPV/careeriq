import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { StartInterview } from '@/components/interview/StartInterview'
import { Alert } from '@/components/ui/Alert'
import { Card } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { PILL_SHAPE } from '@/components/ui/cardStyles'
import { Spinner } from '@/components/ui/Spinner'
import { interviewService } from '@/services/interviewService'
import type { InterviewStatus, InterviewSummary } from '@/types/interview'
import { cn } from '@/utils/cn'

const STATUS: Record<InterviewStatus, { label: string; tone: string }> = {
  CREATED: { label: 'Not started', tone: 'bg-slate-50 text-slate-700 ring-slate-200' },
  IN_PROGRESS: { label: 'In progress', tone: 'bg-sky-50 text-sky-800 ring-sky-200' },
  COMPLETED: { label: 'Finished', tone: 'bg-emerald-50 text-emerald-800 ring-emerald-200' },
  ABANDONED: { label: 'Abandoned', tone: 'bg-slate-50 text-slate-500 ring-slate-200' },
}

function outOfTen(value: string | null): string | null {
  if (value === null) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? (Math.round(parsed * 100) / 10).toFixed(1) : null
}

function InterviewRow({ interview }: { interview: InterviewSummary }) {
  const status = STATUS[interview.status]
  const average = outOfTen(interview.average_score)

  return (
    <li>
      <Link
        to={`/interviews/${interview.id}`}
        className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-4 transition-colors hover:bg-slate-50 sm:px-7"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-slate-900">
            {interview.target_role}
            {/* The company, not the title again: `target_role` already *is* the
                job title on both job-backed paths, so repeating it would only
                give two strings that can disagree. */}
            {interview.target_company && (
              <span className="font-normal text-slate-500"> · {interview.target_company}</span>
            )}
          </p>
          <p className="mt-0.5 text-sm text-slate-500">
            {interview.answered} of {interview.question_budget} answered
            {interview.questions_asked > interview.answered && ' · one waiting for you'}
            {interview.target_job_id && ' · from a posting'}
          </p>
        </div>
        <span className={cn(PILL_SHAPE, status.tone)}>{status.label}</span>
        {/* Null when nothing is marked yet, and shown as a dash rather than a
            zero. A 0 would read as having done badly at an interview nobody
            has marked. */}
        <span className="w-14 text-right text-sm font-medium tabular-nums text-slate-700">
          {average ?? <span className="text-slate-300">—</span>}
        </span>
      </Link>
    </li>
  )
}

export function InterviewsPage() {
  const [items, setItems] = useState<InterviewSummary[] | null>(null)
  const [loadError, setLoadError] = useState(false)

  const load = useCallback(() => {
    interviewService.list().then(
      (response) => setItems(response.items),
      () => setLoadError(true),
    )
  }, [])

  useEffect(load, [load])

  return (
    <div className="space-y-6">
      <PageHeader
        title="Practise interviews"
        description={
          <>
            Paste the posting you are interviewing for and the questions come from what it
            asks for — not a fixed list, and not the corpus average. Answers are marked on five
            things, with the feedback pointing at the words it is about.
          </>
        }
      />

      <Card as="section" aria-labelledby="start-interview">
        <h2 id="start-interview" className="text-base font-semibold text-slate-900">
          Start a new one
        </h2>
        <div className="mt-3">
          <StartInterview />
        </div>
      </Card>

      <section aria-labelledby="past-interviews" className="space-y-3">
        <h2 id="past-interviews" className="text-base font-semibold text-slate-900">
          Your interviews
        </h2>

        {loadError ? (
          <Alert tone="error">We couldn't load your interviews.</Alert>
        ) : items === null ? (
          <div className="flex justify-center py-10">
            <Spinner className="size-6 text-indigo-600" label="Loading interviews" />
          </div>
        ) : items.length === 0 ? (
          <Card tone="dashed" className="text-center">
            <p className="text-sm text-slate-600">
              Nothing here yet. Start one above and it will be waiting whenever you come back.
            </p>
          </Card>
        ) : (
          <Card padded={false}>
            <ul className="divide-y divide-slate-100">
              {items.map((interview) => (
                <InterviewRow key={interview.id} interview={interview} />
              ))}
            </ul>
          </Card>
        )}
      </section>
    </div>
  )
}
