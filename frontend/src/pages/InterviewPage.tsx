import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { CitedAnswer } from '@/components/interview/CitedAnswer'
import { QuestionCard } from '@/components/interview/QuestionCard'
import { TopicProvenance } from '@/components/interview/TopicProvenance'
import { ScoreBreakdown } from '@/components/interview/ScoreBreakdown'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { Textarea } from '@/components/ui/Textarea'
import { useDictation } from '@/hooks/useDictation'
import { interviewService } from '@/services/interviewService'
import type { Interview, InterviewQuestion } from '@/types/interview'

const POLL_MS = 2_000

/**
 * How long to keep polling before saying so.
 *
 * Generation runs after the response is sent, so a failure has no request left
 * to fail on — the server records why in `summary_feedback` when it can, and a
 * process that died mid-task records nothing at all. Without a ceiling the page
 * spins forever on that second case, which is the failure worth designing
 * against.
 */
const POLL_TIMEOUT_MS = 90_000

function Waiting({ label }: { label: string }) {
  return (
    // No `label` on the Spinner: it would add an `sr-only` copy of text that is
    // already visible right beside it, and a screen reader would read the same
    // sentence twice. The Spinner is decorative here and the text carries the
    // meaning, which is what its own comment says it expects.
    <div role="status" className="flex items-center gap-3 py-8 text-sm text-slate-600">
      <Spinner className="size-5 text-indigo-600" />
      <span>{label}</span>
    </div>
  )
}

function AnsweredQuestion({
  question,
  number,
  total,
}: {
  question: InterviewQuestion
  number: number
  total: number
}) {
  const answer = question.answer
  const score = answer?.score ?? null

  return (
    <Card as="article" className="space-y-5">
      <QuestionCard question={question} number={number} total={total} />

      {answer && (
        <div className="space-y-4 border-t border-slate-100 pt-5">
          <h3 className="text-sm font-semibold text-slate-900">What you said</h3>
          <CitedAnswer text={answer.answer_text} spans={score?.cited_spans ?? null} />

          {score ? (
            <div className="space-y-4 border-t border-slate-100 pt-4">
              <ScoreBreakdown score={score} />

              {score.feedback && (
                <p className="text-sm leading-relaxed text-slate-700">{score.feedback}</p>
              )}

              {(score.strengths.length > 0 || score.improvements.length > 0) && (
                <div className="grid gap-4 sm:grid-cols-2">
                  {score.strengths.length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold tracking-wide text-emerald-800 uppercase">
                        Worked
                      </h4>
                      <ul className="mt-1.5 space-y-1 text-sm text-slate-700">
                        {score.strengths.map((item, index) => (
                          <li key={index}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {score.improvements.length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold tracking-wide text-amber-900 uppercase">
                        Next time
                      </h4>
                      <ul className="mt-1.5 space-y-1 text-sm text-slate-700">
                        {score.improvements.map((item, index) => (
                          <li key={index}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : (
            // Not "0" and not silence. The answer is saved either way — it was
            // written before the 202 — and the only thing outstanding is the
            // mark.
            <p className="border-t border-slate-100 pt-4 text-sm text-slate-500">
              Not marked yet. Your answer is saved.
            </p>
          )}
        </div>
      )}
    </Card>
  )
}

export function InterviewPage() {
  const { interviewId = '' } = useParams<{ interviewId: string }>()
  const [interview, setInterview] = useState<Interview | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [draft, setDraft] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [timedOut, setTimedOut] = useState(false)
  const [retrying, setRetrying] = useState(false)
  // Its own, not `submitError`: that one renders inside the answer form, and
  // the whole point of a retry is that there is no form on screen to put it
  // in -- so a failed retry would have said nothing at all.
  const [retryError, setRetryError] = useState<string | null>(null)

  /*
   * Dictated text is *appended*, never substituted.
   *
   * Somebody types a sentence, speaks the next, then fixes a word the recogniser
   * mangled -- all three in one answer. Replacing the box on each final result
   * would throw away whatever they had typed, and separating them by a space
   * only where there is already something is what stops a leading gap.
   */
  const dictation = useDictation(
    useCallback((text: string) => {
      setDraft((current) => {
        const trimmed = text.trim()
        if (!trimmed) return current
        return current ? `${current.trimEnd()} ${trimmed}` : trimmed
      })
    }, []),
  )
  const waitingSince = useRef(Date.now())
  const startedAnswerAt = useRef(Date.now())

  const load = useCallback(() => {
    interviewService.read(interviewId).then(
      (response) => {
        setInterview(response)
        setState('ready')
      },
      () => setState('error'),
    )
  }, [interviewId])

  useEffect(load, [load])

  const questions = interview?.questions ?? []
  const unanswered = questions.find((question) => question.answer === null) ?? null
  const answered = questions.filter((question) => question.answer !== null)
  const finished = interview?.status === 'COMPLETED'

  /**
   * Something is outstanding when there is no question to answer and the
   * interview has not finished, or when an answer is still unmarked.
   *
   * Both are background work, and both end by the transcript changing — so the
   * same poll covers them. It stops when there is nothing left to wait for,
   * because a request that can only return what is already on screen is a
   * request not worth making.
   */
  const awaitingQuestion = !finished && unanswered === null
  const awaitingScore = answered.some((question) => question.answer?.score == null)

  /*
   * A recorded reason stops the wait immediately, and this is the whole point
   * of the field.
   *
   * The server writes `summary_feedback` when it knows the work will not
   * finish -- no resume, no provider, a reply it could not use -- and clears it
   * on any success. Its schema docstring says it is "the difference between
   * 'still thinking' and 'this will never finish'".
   *
   * Until this, the page ignored that and rendered the reason only after the
   * ninety-second timeout, so a failure the server reported on the very first
   * poll sat behind a spinner for a minute and a half. Somebody starting an
   * interview with no resume uploaded watched "Writing your next question…"
   * the entire time, for a question that was never coming.
   */
  const stalled = interview?.summary_feedback != null
  const pending = state === 'ready' && !stalled && (awaitingQuestion || awaitingScore)

  useEffect(() => {
    if (!pending) {
      waitingSince.current = Date.now()
      setTimedOut(false)
      return
    }
    const timer = setInterval(() => {
      if (Date.now() - waitingSince.current > POLL_TIMEOUT_MS) {
        setTimedOut(true)
        return
      }
      load()
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [pending, load])

  // The id, not the object. Every poll returns a fresh `unanswered` with the
  // same id, so depending on the object would restart the clock every two
  // seconds and record every answer as having taken no time at all.
  const unansweredId = unanswered?.id ?? null
  useEffect(() => {
    // A new question means a new clock. `duration_seconds` is not scored — a
    // slow answer is not a worse one — but it is the kind of thing somebody
    // reviewing their own transcript wants to see.
    if (unansweredId !== null) startedAnswerAt.current = Date.now()
  }, [unansweredId])

  function retry() {
    setRetrying(true)
    setRetryError(null)
    interviewService.retry(interviewId).then(
      () => {
        setRetrying(false)
        // The clock restarts with the attempt, so a retry gets its own ninety
        // seconds rather than inheriting whatever was left of the last one.
        waitingSince.current = Date.now()
        setTimedOut(false)
        load()
      },
      (error: unknown) => {
        setRetrying(false)
        setRetryError(
          error instanceof Error && error.message
            ? error.message
            : "We couldn't try that again.",
        )
      },
    )
  }

  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!unanswered || draft.trim().length === 0) return
    setSubmitting(true)
    setSubmitError(null)
    const seconds = Math.round((Date.now() - startedAnswerAt.current) / 1000)
    interviewService.answer(interviewId, unanswered.id, draft, seconds).then(
      () => {
        setSubmitting(false)
        setDraft('')
        waitingSince.current = Date.now()
        load()
      },
      (error: unknown) => {
        setSubmitting(false)
        setSubmitError(
          error instanceof Error && error.message
            ? error.message
            : "We couldn't save that answer. It is still in the box — try again.",
        )
      },
    )
  }

  if (state === 'loading') {
    return (
      <div className="flex justify-center py-16">
        <Spinner className="size-6 text-indigo-600" label="Loading interview" />
      </div>
    )
  }

  if (state === 'error' || interview === null) {
    return (
      <div className="space-y-4">
        <Alert tone="error">We couldn't load that interview.</Alert>
        <Link to="/interviews" className="text-sm font-medium text-indigo-700">
          Back to your interviews
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={interview.target_role}
        description={
          <>
            {answered.length} of {interview.question_budget} answered. Close the tab whenever you
            like — this is saved, and it will be here when you come back.
          </>
        }
        action={
          <Link
            to="/interviews"
            className="text-sm font-medium text-indigo-700 hover:text-indigo-800"
          >
            All interviews
          </Link>
        }
      />

      <TopicProvenance
        source={interview.topic_source}
        postings={interview.topic_postings}
      />

      {answered.map((question, index) => (
        <AnsweredQuestion
          key={question.id}
          question={question}
          number={index + 1}
          total={interview.question_budget}
        />
      ))}

      {unanswered && (
        <Card as="section" className="space-y-5">
          <QuestionCard
            question={unanswered}
            number={answered.length + 1}
            total={interview.question_budget}
          />
          <form onSubmit={submit} className="space-y-3 border-t border-slate-100 pt-5">
            <Textarea
              label="Your answer"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              rows={8}
              maxLength={20_000}
              disabled={submitting}
              hint="Say it the way you would out loud. Rambling is marked separately from being right."
            />

            {/* Hidden where the browser has no recogniser -- Firefox has none at
                all -- rather than disabled, for the reason the Listen button is:
                a control that can never work explains nothing. */}
            {dictation.supported && (
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  variant={dictation.listening ? 'danger' : 'secondary'}
                  size="sm"
                  onClick={() => (dictation.listening ? dictation.stop() : dictation.start())}
                  disabled={submitting}
                >
                  {dictation.listening ? 'Stop speaking' : 'Speak your answer'}
                </Button>
                {dictation.listening && (
                  <span className="text-xs text-slate-500" role="status">
                    {/* The interim transcript, shown but never written into the
                        box. Committing it would rewrite the textarea on every
                        syllable and fight whatever they were editing. */}
                    {dictation.interim
                      ? `“${dictation.interim}”`
                      : 'Listening — speak, and it will appear above.'}
                  </span>
                )}
                {!dictation.listening && (
                  <span className="text-xs text-slate-500">
                    It goes in the box, so you can fix anything it mishears before submitting.
                  </span>
                )}
              </div>
            )}
            {dictation.error && <Alert tone="warning">{dictation.error}</Alert>}

            {submitError && <Alert tone="error">{submitError}</Alert>}
            <div className="flex items-center gap-3">
              <Button type="submit" isLoading={submitting} disabled={draft.trim().length === 0}>
                Submit answer
              </Button>
              <span className="text-xs text-slate-500">
                {draft.trim().length === 0 ? 'Nothing to submit yet.' : 'You cannot change it after.'}
              </span>
            </div>
          </form>
        </Card>
      )}

      {finished && (
        <Alert tone="success" title="That's the whole interview.">
          Read back through your answers above — the highlights show exactly which words each
          piece of feedback is about.
        </Alert>
      )}

      {pending && !timedOut && (
        <Card tone="inset">
          <Waiting
            label={
              awaitingQuestion ? 'Writing your next question…' : 'Marking your answer…'
            }
          />
        </Card>
      )}

      {/* Two different failures, and they deserve two different headings.
          The server saying why is not "taking longer than it should" -- it is
          finished and it did not work, usually for a reason the reader can act
          on. Titling it as slowness invites them to keep waiting. */}
      {stalled && (
        <Alert
          tone="warning"
          // `summary_feedback` is set mid-interview too -- a mark that could not
          // be produced, a question the model kept failing -- and "could not
          // start" would be plainly false once there is a transcript above it.
          title={
            questions.length === 0
              ? 'This interview could not start.'
              : 'This interview cannot go on.'
          }
        >
          <p>{interview.summary_feedback}</p>
          {/* A provider outage is usually over in a minute, and before this the
              only way forward was starting again -- which mid-interview meant
              abandoning every answer already given and marked. */}
          <Button
            variant="secondary"
            size="sm"
            className="mt-3"
            onClick={retry}
            isLoading={retrying}
          >
            Try again
          </Button>
          {retryError && <p className="mt-2 text-sm font-medium">{retryError}</p>}
        </Alert>
      )}

      {timedOut && !stalled && (
        <Alert tone="warning" title="This is taking longer than it should.">
          {/* No `summary_feedback` branch here any more: `!stalled` means there
              is none, so the other half of that ternary was unreachable. This
              is the silent failure -- a background task whose process died
              without recording anything, which is the case the timeout exists
              for at all. */}
          <p>
            Nothing has arrived for a while and the server has not said why. Anything you have
            already answered is saved.
          </p>
          <Button
            variant="secondary"
            size="sm"
            className="mt-3"
            onClick={retry}
            isLoading={retrying}
          >
            Try again
          </Button>
          {retryError && <p className="mt-2 text-sm font-medium">{retryError}</p>}
        </Alert>
      )}
    </div>
  )
}
