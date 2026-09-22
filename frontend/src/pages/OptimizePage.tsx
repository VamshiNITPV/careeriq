import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { optimizationService } from '@/services/optimizationService'
import type { AnalysisResponse, ApplyResult, Suggestion } from '@/types/optimization'
import { cn } from '@/utils/cn'
import { cardClass } from '@/components/ui/cardStyles'
import { PageHeader } from '@/components/ui/PageHeader'

/**
 * Review tailored rewrites, one at a time (US-6.1 AC1).
 *
 * **Every suggestion is accepted or rejected individually.** No "apply all":
 * these are claims about the reader's own work, and a single button asks them
 * to endorse text they have not read. The reviewing is the feature.
 *
 * The original resume is never changed. Applying produces a new version, which
 * is what makes "undo" mean opening the previous one.
 */

/** How often to re-check while the model is working. */
const POLL_MS = 2000
/** Give up after this long rather than spinning forever on a stuck row. */
const POLL_TIMEOUT_MS = 90_000

function DiffRow({ label, text, tone }: { label: string; text: string; tone: 'old' | 'new' }) {
  return (
    <div
      className={cn(
        'rounded-lg border p-3',
        tone === 'old' ? 'border-slate-200 bg-slate-50' : 'border-indigo-200 bg-indigo-50',
      )}
    >
      <p
        className={cn(
          'text-[11px] font-semibold tracking-wide uppercase',
          tone === 'old' ? 'text-slate-500' : 'text-indigo-700',
        )}
      >
        {label}
      </p>
      <p
        className={cn(
          'mt-1 text-sm break-words',
          tone === 'old' ? 'text-slate-600' : 'text-slate-900',
        )}
      >
        {text}
      </p>
    </div>
  )
}

function SuggestionCard({
  suggestion,
  choice,
  onChoose,
}: {
  suggestion: Suggestion
  choice: 'accepted' | 'rejected' | undefined
  onChoose: (next: 'accepted' | 'rejected' | undefined) => void
}) {
  const otherSources = suggestion.grounded_in.filter(
    (line) => line.trim() !== suggestion.original.trim(),
  )

  return (
    <li className={cardClass()}>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-sm font-medium text-slate-900">
          {suggestion.position}. {suggestion.section || 'resume'}
        </span>
      </div>

      {/* Both texts, always. Showing only the rewrite would ask someone to
          approve a change they cannot see. */}
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <DiffRow label="Your resume says" text={suggestion.original} tone="old" />
        <DiffRow label="Suggested" text={suggestion.suggested} tone="new" />
      </div>

      {suggestion.rationale && (
        <p className="mt-3 text-sm text-slate-600">{suggestion.rationale}</p>
      )}

      {/* Only the sources that say something the panel above does not. A model
          usually cites the very line being rewritten, and repeating it under
          "what this is based on" is noise that makes the real extra sources
          harder to notice. */}
      {otherSources.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-slate-500">
            Also based on
          </summary>
          <ul className="mt-1 space-y-1 border-l-2 border-slate-200 pl-3">
            {otherSources.map((line) => (
              <li key={line} className="text-xs text-slate-500 italic">
                {line}
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          size="sm"
          variant={choice === 'accepted' ? 'primary' : 'secondary'}
          aria-pressed={choice === 'accepted'}
          onClick={() => onChoose(choice === 'accepted' ? undefined : 'accepted')}
        >
          Use this
        </Button>
        <Button
          size="sm"
          variant={choice === 'rejected' ? 'primary' : 'secondary'}
          aria-pressed={choice === 'rejected'}
          onClick={() => onChoose(choice === 'rejected' ? undefined : 'rejected')}
        >
          Skip
        </Button>
      </div>
    </li>
  )
}

export function OptimizePage() {
  const { analysisId = '' } = useParams<{ analysisId: string }>()
  const [result, setResult] = useState<AnalysisResponse | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [choices, setChoices] = useState<Record<string, 'accepted' | 'rejected'>>({})
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const [applied, setApplied] = useState<ApplyResult | null>(null)
  const startedAt = useRef(Date.now())
  const [timedOut, setTimedOut] = useState(false)

  const load = useCallback(() => {
    optimizationService.read(analysisId).then(
      (response) => {
        setResult(response)
        setState('ready')
      },
      () => setState('error'),
    )
  }, [analysisId])

  useEffect(load, [load])

  // Poll only while the work is actually outstanding. A COMPLETE or FAILED row
  // never changes again, so continuing would be requests that can only return
  // what is already on screen.
  const pending = result?.status === 'PENDING' || result?.status === 'RUNNING'
  useEffect(() => {
    if (!pending || timedOut) return
    const timer = setInterval(() => {
      if (Date.now() - startedAt.current > POLL_TIMEOUT_MS) {
        setTimedOut(true)
        return
      }
      load()
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [pending, timedOut, load])

  const acceptedIds = Object.entries(choices)
    .filter(([, value]) => value === 'accepted')
    .map(([id]) => id)

  const undecided = (result?.suggestions ?? []).filter((s) => !choices[s.id]).length

  function apply() {
    setApplying(true)
    setApplyError(null)
    optimizationService.apply(analysisId, acceptedIds).then(
      (response) => {
        setApplying(false)
        setApplied(response)
      },
      (error: unknown) => {
        setApplying(false)
        setApplyError(
          error instanceof Error && error.message
            ? error.message
            : "We couldn't save those changes.",
        )
      },
    )
  }

  return (
    <div className="space-y-6">
      <header>
        <PageHeader
          title="Tailor your resume"
          description={
            <>Rewrites of what your resume already says. Nothing here adds a skill, employer or number
          you have not written down.</>
          }
        />
      </header>

      {state === 'loading' ? (
        <div className="flex justify-center py-12">
          <Spinner className="size-6 text-indigo-600" label="Loading suggestions" />
        </div>
      ) : state === 'error' ? (
        <div className="space-y-3">
          <Alert tone="error">
            We couldn&apos;t load these suggestions. This is a problem on our side.
          </Alert>
          <Button variant="secondary" size="sm" onClick={load}>
            Try again
          </Button>
        </div>
      ) : result === null ? null : applied ? (
        <section className={cardClass()}>
          <p className="text-sm font-medium text-slate-900">{applied.message}</p>
          <p className="mt-1 text-sm text-slate-600">
            {/* Named explicitly, because a "new version" that silently replaced
                the old one would be a different and much worse promise. */}
            Your original resume is unchanged — this is a new version alongside it.
          </p>
          {/* Straight at the new version, not the resume list. "Created
              version 3" with nowhere to go makes the reader hunt for what they
              just made. */}
          <Link
            to={`/resume/${applied.resume_id}?v=${applied.resume_version_id}`}
            className="mt-4 inline-block text-sm font-medium text-indigo-600 underline"
          >
            See version {applied.version_number}
          </Link>
        </section>
      ) : result.status === 'FAILED' ? (
        <div className="space-y-3">
          <Alert tone="error">{result.error ?? 'This analysis could not be completed.'}</Alert>
          {/* A way out. The reason is stored on the row, so reloading this page
              shows the same failure forever — the only thing that helps is
              starting a new analysis, and without this link the reader has to
              work out for themselves that they must navigate back to the job. */}
          <p className="text-sm text-slate-600">
            This result is from the attempt that failed and won&apos;t change.{' '}
            <Link to={`/jobs/${result.job_id}`} className="font-medium text-indigo-600 underline">
              Go back to the job
            </Link>{' '}
            to try again.
          </p>
        </div>
      ) : timedOut ? (
        <div className="space-y-3">
          <Alert tone="warning">
            This is taking longer than expected. It may still finish — reload to check.
          </Alert>
          <Button variant="secondary" size="sm" onClick={load}>
            Check again
          </Button>
        </div>
      ) : pending ? (
        <div className="flex flex-col items-center gap-3 py-12">
          <Spinner className="size-6 text-indigo-600" label="Writing suggestions" />
          <p className="text-sm text-slate-600">Reading your resume against this job…</p>
        </div>
      ) : (
        <>
          {result.suggestions.length === 0 ? (
            <section className={cardClass()}>
              <p className="text-sm font-medium text-slate-900">No changes to suggest.</p>
              <p className="mt-1 text-sm text-slate-600">
                {result.rejected_by_validator > 0
                  ? `We withheld ${result.rejected_by_validator} ${
                      result.rejected_by_validator === 1 ? 'suggestion' : 'suggestions'
                    } that would have added something your resume doesn't say.`
                  : 'Your wording already covers what this job asks for.'}
              </p>
            </section>
          ) : (
            <>
              <ul className="space-y-4">
                {result.suggestions.map((suggestion) => (
                  <SuggestionCard
                    key={suggestion.id}
                    suggestion={suggestion}
                    choice={choices[suggestion.id]}
                    onChoose={(next) =>
                      setChoices((current) => {
                        const { [suggestion.id]: _removed, ...rest } = current
                        return next ? { ...rest, [suggestion.id]: next } : rest
                      })
                    }
                  />
                ))}
              </ul>

              {applyError && <Alert tone="error">{applyError}</Alert>}

              <section className={cardClass()}>
                <p className="text-sm text-slate-700" role="status">
                  {acceptedIds.length} of {result.suggestions.length} selected
                  {undecided > 0 && ` · ${undecided} still to review`}
                </p>
                <Button
                  className="mt-3"
                  disabled={acceptedIds.length === 0 || applying}
                  onClick={apply}
                >
                  {applying ? 'Saving…' : 'Save as a new version'}
                </Button>
                <p className="mt-2 text-xs text-slate-500">
                  Creates a new version. Your original resume is not changed.
                </p>
              </section>
            </>
          )}

          {result.rejected_by_validator > 0 && result.suggestions.length > 0 && (
            <p className="text-xs text-slate-500">
              {/* Reported rather than hidden: an unexplained short list invites
                  the reader to assume the model had nothing to say, when in fact
                  something was caught. */}
              {result.rejected_by_validator} further{' '}
              {result.rejected_by_validator === 1 ? 'suggestion was' : 'suggestions were'} withheld
              for claiming something your resume does not say.
            </p>
          )}
        </>
      )}
    </div>
  )
}
