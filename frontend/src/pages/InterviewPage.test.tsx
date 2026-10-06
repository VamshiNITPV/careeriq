import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { interviewService } from '@/services/interviewService'
import type {
  AnswerScore,
  Interview,
  InterviewQuestion,
} from '@/types/interview'

import { InterviewPage } from './InterviewPage'

const ANSWER = 'I used dual writes during the cutover, then verified row counts matched.'

function score(overrides: Partial<AnswerScore> = {}): AnswerScore {
  return {
    technical_score: '0.800',
    relevance_score: '0.900',
    completeness_score: '0.600',
    communication_score: '0.400',
    structure_score: '0.300',
    overall_score: '0.600',
    feedback: 'Solid on the technique, thin on the rollback.',
    strengths: ['names a concrete technique'],
    improvements: ['say what you would do if parity failed'],
    cited_spans: null,
    next_difficulty: 'HARD',
    ...overrides,
  }
}

function question(overrides: Partial<InterviewQuestion> = {}): InterviewQuestion {
  return {
    id: 'q1',
    question_order: 1,
    question_text: 'How would you migrate a ledger with no downtime?',
    topic: 'Schema migrations',
    difficulty: 'MEDIUM',
    // Deliberately sharing no words with ANSWER. The rubric is rendered on the
    // page (collapsed, not hidden), so a phrase appearing in both would make
    // every assertion about the answer ambiguous.
    expected_points: ['names a concrete technique', 'explains how parity is confirmed'],
    grounded_in: null,
    degraded: false,
    asked_at: '2026-09-23T10:00:00Z',
    answer: null,
    ...overrides,
  }
}

function interview(overrides: Partial<Interview> = {}): Interview {
  return {
    id: 'i1',
    target_role: 'Backend Engineer',
    target_job_id: null,
    status: 'IN_PROGRESS',
    current_difficulty: 'MEDIUM',
    topics_covered: [],
    questions_asked: 1,
    question_budget: 10,
    questions: [question()],
    topic_source: 'ROLE_DEMAND',
    topic_postings: 12,
    created_at: '2026-09-23T10:00:00Z',
    summary_feedback: null,
    ...overrides,
  }
}

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/interviews/i1']}>
      <Routes>
        <Route path="/interviews/:interviewId" element={<InterviewPage />} />
      </Routes>
    </MemoryRouter>,
  )

describe('InterviewPage', () => {
  beforeEach(() => vi.restoreAllMocks())
  afterEach(() => vi.useRealTimers())

  it('shows the question waiting to be answered', async () => {
    vi.spyOn(interviewService, 'read').mockResolvedValue(interview())

    renderPage()

    expect(
      await screen.findByText('How would you migrate a ledger with no downtime?'),
    ).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /your answer/i })).toBeInTheDocument()
  })

  it('says where the topics came from', async () => {
    // Wiring only -- the four renderings are covered in TopicProvenance's own
    // tests. This catches the component being present but never rendered.
    vi.spyOn(interviewService, 'read').mockResolvedValue(interview())

    renderPage()

    expect(
      await screen.findByText(/12 live postings for this role/i),
    ).toBeInTheDocument()
  })

  it('claims nothing about topics before the first question exists', async () => {
    vi.spyOn(interviewService, 'read').mockResolvedValue(
      interview({ questions: [], questions_asked: 0, topic_source: null, topic_postings: null }),
    )

    renderPage()
    await screen.findByText(/writing your next question/i)

    expect(screen.queryByText(/for this role/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/general topics/i)).not.toBeInTheDocument()
  })

  it('shows a recorded failure at once instead of spinning for ninety seconds', async () => {
    /*
     * The bug this replaces: `summary_feedback` was rendered only inside the
     * timeout branch, so a reason the server wrote before the first poll sat
     * behind "Writing your next question…" for a minute and a half. Somebody
     * starting an interview with no resume watched a spinner for a question
     * that was never coming.
     *
     * No fake timers here on purpose -- the point is that this appears without
     * any time passing at all.
     */
    vi.spyOn(interviewService, 'read').mockResolvedValue(
      interview({
        questions: [],
        questions_asked: 0,
        topic_source: null,
        topic_postings: null,
        summary_feedback: 'Upload and process a resume first.',
      }),
    )

    renderPage()

    expect(await screen.findByText(/could not start/i)).toBeInTheDocument()
    expect(screen.getByText('Upload and process a resume first.')).toBeInTheDocument()
    expect(screen.queryByText(/writing your next question/i)).not.toBeInTheDocument()
  })

  it('stops polling once the server has said why', async () => {
    // A reason means the work will not finish. Continuing to ask can only
    // return what is already on screen.
    const read = vi.spyOn(interviewService, 'read').mockResolvedValue(
      interview({ questions: [], summary_feedback: 'The model refused.' }),
    )

    renderPage()
    await screen.findByText('The model refused.')
    const callsSoFar = read.mock.calls.length

    vi.useFakeTimers({ shouldAdvanceTime: true })
    await vi.advanceTimersByTimeAsync(30_000)
    vi.useRealTimers()

    expect(read.mock.calls.length).toBe(callsSoFar)
  })

  it('does not say an interview could not start when it plainly did', async () => {
    // `summary_feedback` is set mid-interview too. With a transcript above it,
    // "could not start" would be false.
    vi.spyOn(interviewService, 'read').mockResolvedValue(
      interview({
        questions: [
          question({
            answer: {
              answer_text: ANSWER,
              duration_seconds: null,
              submitted_at: '2026-09-23T10:05:00Z',
              score: score(),
            },
          }),
        ],
        summary_feedback: 'Could not mark that answer.',
      }),
    )

    renderPage()

    expect(await screen.findByText(/cannot go on/i)).toBeInTheDocument()
    expect(screen.queryByText(/could not start/i)).not.toBeInTheDocument()
  })

  describe('speaking an answer', () => {
    let engines: { onresult: ((event: unknown) => void) | null; abort: ReturnType<typeof vi.fn> }[]

    function installRecogniser() {
      engines = []
      ;(window as unknown as Record<string, unknown>).SpeechRecognition = function (
        this: Record<string, unknown>,
      ) {
        this.continuous = false
        this.interimResults = false
        this.lang = ''
        this.start = vi.fn()
        this.stop = vi.fn()
        this.abort = vi.fn()
        this.onresult = null
        this.onerror = null
        this.onend = null
        engines.push(this as never)
      }
    }

    function say(text: string) {
      const entry = [{ transcript: text }] as unknown as ArrayLike<{ transcript: string }> & {
        isFinal: boolean
      }
      entry.isFinal = true
      engines.at(-1)?.onresult?.({ resultIndex: 0, results: [entry] })
    }

    afterEach(() => {
      delete (window as unknown as Record<string, unknown>).SpeechRecognition
    })

    it('offers no microphone where the browser has none', async () => {
      // jsdom, and Firefox, which has no recogniser at all.
      vi.spyOn(interviewService, 'read').mockResolvedValue(interview())

      renderPage()
      await screen.findByRole('textbox', { name: /your answer/i })

      expect(screen.queryByRole('button', { name: /speak your answer/i })).not.toBeInTheDocument()
    })

    it('puts what was said into the box, so it can be corrected', async () => {
      /*
       * The point of the whole feature. Recognition mangles exactly the
       * vocabulary an interview answer is made of -- "FastAPI", "p99",
       * "idempotent" -- and the answer is then marked on technical
       * correctness. It has to land somewhere editable.
       */
      const user = userEvent.setup()
      installRecogniser()
      vi.spyOn(interviewService, 'read').mockResolvedValue(interview())

      renderPage()
      await user.click(await screen.findByRole('button', { name: /speak your answer/i }))
      act(() => say('I would use dual writes.'))

      expect(screen.getByRole('textbox', { name: /your answer/i })).toHaveValue(
        'I would use dual writes.',
      )
    })

    it('appends to what was already typed rather than replacing it', async () => {
      // Somebody types a sentence, speaks the next, then fixes a mangled word.
      // Replacing would throw away the first.
      const user = userEvent.setup()
      installRecogniser()
      vi.spyOn(interviewService, 'read').mockResolvedValue(interview())

      renderPage()
      const box = await screen.findByRole('textbox', { name: /your answer/i })
      await user.type(box, 'First I would check the plan.')
      await user.click(screen.getByRole('button', { name: /speak your answer/i }))
      act(() => say('Then I would add an index.'))

      expect(box).toHaveValue('First I would check the plan. Then I would add an index.')
    })

    it('offers to stop once it is listening', async () => {
      const user = userEvent.setup()
      installRecogniser()
      vi.spyOn(interviewService, 'read').mockResolvedValue(interview())

      renderPage()
      await user.click(await screen.findByRole('button', { name: /speak your answer/i }))

      expect(screen.getByRole('button', { name: /stop speaking/i })).toBeInTheDocument()
    })
  })

  describe('trying again', () => {
    const failed = () =>
      interview({
        questions: [],
        questions_asked: 0,
        topic_source: null,
        topic_postings: null,
        summary_feedback: 'The AI provider could not be reached just now.',
      })

    it('offers a retry on a recorded failure', async () => {
      // A provider outage is usually over in a minute. Before this the only way
      // forward was starting again, which mid-interview meant abandoning every
      // answer already given and marked.
      vi.spyOn(interviewService, 'read').mockResolvedValue(failed())

      renderPage()

      expect(await screen.findByRole('button', { name: /try again/i })).toBeInTheDocument()
    })

    it('asks the server to try, then reloads', async () => {
      const user = userEvent.setup()
      const read = vi.spyOn(interviewService, 'read').mockResolvedValue(failed())
      const retry = vi
        .spyOn(interviewService, 'retry')
        .mockResolvedValue({ interview_id: 'i1', status: 'CREATED', poll_url: '/x' })

      renderPage()
      await user.click(await screen.findByRole('button', { name: /try again/i }))

      await waitFor(() => expect(retry).toHaveBeenCalledWith('i1'))
      // Reloaded, so the cleared reason and any new question are picked up
      // without waiting for the next poll.
      await waitFor(() => expect(read.mock.calls.length).toBeGreaterThan(1))
    })

    it('says so when the retry itself fails', async () => {
      const user = userEvent.setup()
      vi.spyOn(interviewService, 'read').mockResolvedValue(failed())
      vi.spyOn(interviewService, 'retry').mockRejectedValue(
        new Error('There is already a question waiting for your answer.'),
      )

      renderPage()
      await user.click(await screen.findByRole('button', { name: /try again/i }))

      expect(
        await screen.findByText(/already a question waiting/i),
      ).toBeInTheDocument()
    })

    it('offers no retry while a question is waiting to be answered', async () => {
      // The server refuses it with a 409, so offering the button would promise
      // something that cannot happen.
      vi.spyOn(interviewService, 'read').mockResolvedValue(interview())

      renderPage()
      await screen.findByRole('textbox', { name: /your answer/i })

      expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
    })
  })

  it('will not submit an empty answer', async () => {
    vi.spyOn(interviewService, 'read').mockResolvedValue(interview())
    const answer = vi.spyOn(interviewService, 'answer')

    renderPage()
    await screen.findByRole('textbox', { name: /your answer/i })

    expect(screen.getByRole('button', { name: /submit answer/i })).toBeDisabled()
    expect(answer).not.toHaveBeenCalled()
  })

  it('sends what was typed and reloads', async () => {
    const user = userEvent.setup()
    vi.spyOn(interviewService, 'read').mockResolvedValue(interview())
    const answer = vi
      .spyOn(interviewService, 'answer')
      .mockResolvedValue({ interview_id: 'i1', status: 'IN_PROGRESS', poll_url: '/x' })

    renderPage()
    await user.type(
      await screen.findByRole('textbox', { name: /your answer/i }),
      'Dual writes.',
    )
    await user.click(screen.getByRole('button', { name: /submit answer/i }))

    await waitFor(() => expect(answer).toHaveBeenCalled())
    expect(answer.mock.calls[0]?.[0]).toBe('i1')
    expect(answer.mock.calls[0]?.[1]).toBe('q1')
    expect(answer.mock.calls[0]?.[2]).toBe('Dual writes.')
  })

  it('keeps the answer in the box when saving fails', async () => {
    // The one thing here that cannot be recovered by retrying is text the user
    // typed and the page threw away.
    const user = userEvent.setup()
    vi.spyOn(interviewService, 'read').mockResolvedValue(interview())
    vi.spyOn(interviewService, 'answer').mockRejectedValue(new Error('nope'))

    renderPage()
    const box = await screen.findByRole('textbox', { name: /your answer/i })
    await user.type(box, 'Dual writes.')
    await user.click(screen.getByRole('button', { name: /submit answer/i }))

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(box).toHaveValue('Dual writes.')
  })

  describe('a marked answer', () => {
    const marked = () =>
      interview({
        status: 'COMPLETED',
        questions: [
          question({
            answer: {
              answer_text: ANSWER,
              duration_seconds: 90,
              submitted_at: '2026-09-23T10:05:00Z',
              score: score(),
            },
          }),
        ],
      })

    it('shows all five dimensions, not just the overall', async () => {
      vi.spyOn(interviewService, 'read').mockResolvedValue(marked())

      renderPage()

      // The whole point of the five-dimension design: an answer that is right
      // and badly delivered should read as exactly that on screen.
      for (const name of ['technical', 'relevance', 'completeness', 'communication', 'structure']) {
        expect(await screen.findByText(name)).toBeInTheDocument()
      }
    })

    it('shows the feedback and what to do next time', async () => {
      vi.spyOn(interviewService, 'read').mockResolvedValue(marked())

      renderPage()

      expect(
        await screen.findByText('Solid on the technique, thin on the rollback.'),
      ).toBeInTheDocument()
      expect(screen.getByText('say what you would do if parity failed')).toBeInTheDocument()
    })

    it('says an answer is saved but unmarked rather than showing a zero', async () => {
      // A 0 would read as having done badly at something nobody has marked.
      vi.spyOn(interviewService, 'read').mockResolvedValue(
        interview({
          status: 'COMPLETED',
          questions: [
            question({
              answer: {
                answer_text: ANSWER,
                duration_seconds: null,
                submitted_at: '2026-09-23T10:05:00Z',
                score: null,
              },
            }),
          ],
        }),
      )

      renderPage()

      expect(await screen.findByText(/not marked yet/i)).toBeInTheDocument()
      expect(screen.queryByText('0.0')).not.toBeInTheDocument()
    })
  })

  describe('citations', () => {
    it('marks the cited words inside the answer', async () => {
      const start = ANSWER.indexOf('dual writes')
      vi.spyOn(interviewService, 'read').mockResolvedValue(
        interview({
          status: 'COMPLETED',
          questions: [
            question({
              answer: {
                answer_text: ANSWER,
                duration_seconds: null,
                submitted_at: '2026-09-23T10:05:00Z',
                score: score({
                  cited_spans: [
                    {
                      start,
                      end: start + 'dual writes'.length,
                      text: 'dual writes',
                      note: 'the technique',
                    },
                  ],
                }),
              },
            }),
          ],
        }),
      )

      renderPage()

      const highlight = await screen.findByText('dual writes')
      expect(highlight.tagName).toBe('MARK')
      expect(screen.getByText('the technique')).toBeInTheDocument()
    })

    it('renders the answer intact when a span lies about its own text', async () => {
      // The rendered text comes from the answer at the offsets, never from the
      // model's copy of it. The server checks the two agree; this means a
      // disagreement could not reach the reader even if that check stopped.
      const start = ANSWER.indexOf('dual writes')
      vi.spyOn(interviewService, 'read').mockResolvedValue(
        interview({
          status: 'COMPLETED',
          questions: [
            question({
              answer: {
                answer_text: ANSWER,
                duration_seconds: null,
                submitted_at: '2026-09-23T10:05:00Z',
                score: score({
                  cited_spans: [
                    {
                      start,
                      end: start + 'dual writes'.length,
                      text: 'something the candidate never wrote',
                      note: '',
                    },
                  ],
                }),
              },
            }),
          ],
        }),
      )

      renderPage()

      expect(await screen.findByText('dual writes')).toBeInTheDocument()
      expect(
        screen.queryByText(/something the candidate never wrote/),
      ).not.toBeInTheDocument()
    })
  })

  describe('while something is outstanding', () => {
    it('says the next question is being written', async () => {
      vi.spyOn(interviewService, 'read').mockResolvedValue(
        interview({
          questions: [
            question({
              answer: {
                answer_text: ANSWER,
                duration_seconds: null,
                submitted_at: '2026-09-23T10:05:00Z',
                score: score(),
              },
            }),
          ],
        }),
      )

      renderPage()

      expect(await screen.findByText(/writing your next question/i)).toBeInTheDocument()
    })

    it('stops waiting once the interview is finished', async () => {
      // A COMPLETED interview never changes again, so a spinner there is a
      // promise of something that is not coming.
      vi.spyOn(interviewService, 'read').mockResolvedValue(
        interview({
          status: 'COMPLETED',
          questions: [
            question({
              answer: {
                answer_text: ANSWER,
                duration_seconds: null,
                submitted_at: '2026-09-23T10:05:00Z',
                score: score(),
              },
            }),
          ],
        }),
      )

      renderPage()
      await screen.findByText(/that's the whole interview/i)

      expect(screen.queryByText(/writing your next question/i)).not.toBeInTheDocument()
    })
  })

  it('gives up eventually when the server never said why', async () => {
    /*
     * The timeout branch, and the only case left for it.
     *
     * A recorded `summary_feedback` now stops the wait at once, so what this
     * covers is the other failure: a background task whose process died and
     * wrote nothing at all. Without a ceiling the page spins forever on it.
     *
     * `shouldAdvanceTime` so findBy/waitFor still work, and the fake clock is
     * installed *before* render because the poll's setInterval is created
     * during it -- a clock swapped in afterwards would never drive it.
     */
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.spyOn(interviewService, 'read').mockResolvedValue(
      interview({ questions: [], questions_asked: 0, summary_feedback: null }),
    )

    renderPage()
    await screen.findByText(/writing your next question/i)

    await vi.advanceTimersByTimeAsync(95_000)

    await waitFor(() =>
      expect(screen.getByText(/has not said why/i)).toBeInTheDocument(),
    )
    expect(screen.queryByText(/writing your next question/i)).not.toBeInTheDocument()
  })

  it('reports a session it cannot load instead of an empty page', async () => {
    vi.spyOn(interviewService, 'read').mockRejectedValue(new Error('gone'))

    renderPage()

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(/couldn't load that interview/i)).toBeInTheDocument()
  })
})
