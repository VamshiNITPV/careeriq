import { render, screen, waitFor, within } from '@testing-library/react'
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

  it('stops polling eventually and says why nothing arrived', async () => {
    // `shouldAdvanceTime` so findBy/waitFor still work: the fake clock has to
    // be installed *before* render, because the poll's setInterval is created
    // during it and a clock swapped in afterwards would never drive it.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.spyOn(interviewService, 'read').mockResolvedValue(
      interview({ questions: [], questions_asked: 0, summary_feedback: 'The model refused.' }),
    )

    renderPage()
    await screen.findByText(/writing your next question/i)

    // Generation runs after the response is sent, so a failure has no request
    // left to fail on. Without a ceiling this page spins forever on a task
    // whose process died, which is the failure worth designing against.
    await vi.advanceTimersByTimeAsync(95_000)

    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument())
    expect(screen.getByText('The model refused.')).toBeInTheDocument()
    expect(screen.queryByText(/writing your next question/i)).not.toBeInTheDocument()
  })

  it('reports a session it cannot load instead of an empty page', async () => {
    vi.spyOn(interviewService, 'read').mockRejectedValue(new Error('gone'))

    renderPage()

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(/couldn't load that interview/i)).toBeInTheDocument()
  })
})
