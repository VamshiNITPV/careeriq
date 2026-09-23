import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { InterviewQuestion } from '@/types/interview'

import { QuestionCard } from './QuestionCard'

function question(overrides: Partial<InterviewQuestion> = {}): InterviewQuestion {
  return {
    id: 'q1',
    question_order: 1,
    question_text: 'How would you migrate a ledger with no downtime?',
    topic: 'Schema migrations',
    difficulty: 'MEDIUM',
    expected_points: ['names a concrete technique'],
    grounded_in: null,
    degraded: false,
    asked_at: '2026-09-23T10:00:00Z',
    answer: null,
    ...overrides,
  }
}

const renderCard = (overrides: Partial<InterviewQuestion> = {}) =>
  render(<QuestionCard question={question(overrides)} number={1} total={10} />)

describe('QuestionCard', () => {
  it('shows the question, its topic and its difficulty', () => {
    renderCard()

    expect(screen.getByText(/how would you migrate a ledger/i)).toBeInTheDocument()
    expect(screen.getByText('Schema migrations')).toBeInTheDocument()
    expect(screen.getByText('medium')).toBeInTheDocument()
  })

  describe('why this question was asked', () => {
    /*
     * Three states, and the third was invisible until a run against the real
     * model surfaced it. Asked to build an AI Engineer question on a backend
     * engineer's payments resume, the model returned no grounding at all —
     * which is the fabrication guard working, not failing.
     */

    it('quotes the resume words it was built on', () => {
      renderCard({ grounded_in: 'Migrated the ledger from MySQL to PostgreSQL' })

      expect(screen.getByText(/asked because your resume says/i)).toBeInTheDocument()
      expect(
        screen.getByText(/Migrated the ledger from MySQL to PostgreSQL/),
      ).toBeInTheDocument()
    })

    it('says a question is not personalised when grounding was rejected', () => {
      renderCard({ degraded: true })

      expect(screen.getByText('not personalised')).toBeInTheDocument()
    })

    it('explains an ungrounded question rather than showing it in silence', () => {
      // Silence would read as the grounded case with the quote left off, on a
      // page whose headline claim is "built from your resume".
      renderCard({ grounded_in: null, degraded: false })

      expect(screen.getByText(/a general question for this role/i)).toBeInTheDocument()
      expect(screen.queryByText('not personalised')).not.toBeInTheDocument()
    })

    it('does not explain twice when a question is both degraded and ungrounded', () => {
      // `degraded` already carries the message, and two notices for one
      // condition read as two separate problems.
      renderCard({ grounded_in: null, degraded: true })

      expect(screen.getByText('not personalised')).toBeInTheDocument()
      expect(screen.queryByText(/a general question for this role/i)).not.toBeInTheDocument()
    })

    it('shows the quote rather than the explanation when it has one', () => {
      renderCard({ grounded_in: 'Reduced p99 latency by 35%' })

      expect(screen.queryByText(/a general question for this role/i)).not.toBeInTheDocument()
    })
  })

  it('offers the rubric, and says reading it cannot change the mark', () => {
    // Shown before the answer is written, which no real interview does. The
    // rubric was fixed before the answer existed, so it cannot change the mark,
    // and practising with no idea what a strong answer contains is practising
    // in the dark.
    renderCard()

    expect(screen.getByText('names a concrete technique')).toBeInTheDocument()
    expect(screen.getByText(/cannot change your mark/i)).toBeInTheDocument()
  })
})
