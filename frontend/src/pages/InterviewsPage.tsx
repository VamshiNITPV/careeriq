import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
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
          <p className="truncate font-medium text-slate-900">{interview.target_role}</p>
          <p className="mt-0.5 text-sm text-slate-500">
            {interview.answered} of {interview.question_budget} answered
            {interview.questions_asked > interview.answered && ' · one waiting for you'}
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
  const navigate = useNavigate()
  const [items, setItems] = useState<InterviewSummary[] | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [role, setRole] = useState('')
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)

  const load = useCallback(() => {
    interviewService.list().then(
      (response) => setItems(response.items),
      () => setLoadError(true),
    )
  }, [])

  useEffect(load, [load])

  function start(event: React.FormEvent) {
    event.preventDefault()
    const target = role.trim()
    if (target.length < 2) {
      setStartError('Tell us the role you are preparing for.')
      return
    }
    setStarting(true)
    setStartError(null)
    interviewService.start({ target_role: target }).then(
      (started) => navigate(`/interviews/${started.interview_id}`),
      (error: unknown) => {
        setStarting(false)
        setStartError(
          error instanceof Error && error.message
            ? error.message
            : "We couldn't start that interview.",
        )
      },
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Practise interviews"
        description={
          <>
            Questions built from what this role's postings actually ask for and from your own
            resume — not a fixed list. Answers are marked on five things, with the feedback
            pointing at the words it is about.
          </>
        }
      />

      <Card as="section" aria-labelledby="start-interview">
        <h2 id="start-interview" className="text-base font-semibold text-slate-900">
          Start a new one
        </h2>
        <form onSubmit={start} className="mt-3 flex flex-wrap items-end gap-3">
          <div className="min-w-56 flex-1">
            <Input
              label="Role you are preparing for"
              value={role}
              onChange={(event) => setRole(event.target.value)}
              placeholder="AI Engineer"
              // Free text rather than a picker: somebody can rehearse for a
              // role this corpus has never carried a posting for, and making
              // them choose from a list would fail exactly the person
              // preparing for something they have not found yet.
              maxLength={200}
              disabled={starting}
            />
          </div>
          <Button type="submit" isLoading={starting}>
            Start
          </Button>
        </form>
        {startError && (
          <Alert tone="error" className="mt-3">
            {startError}
          </Alert>
        )}
        <p className="mt-3 text-xs text-slate-500">
          Ten questions, and it adapts as you go — a strong answer moves on, a weak one stays
          on the topic and gets easier. You can close the tab and come back.
        </p>
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
