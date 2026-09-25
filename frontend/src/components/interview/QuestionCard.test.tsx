import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
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

  describe('hearing the question', () => {
    afterEach(() => {
      delete (window as unknown as Record<string, unknown>).speechSynthesis
      delete (window as unknown as Record<string, unknown>).SpeechSynthesisUtterance
    })

    function installEngine() {
      const engine = { speak: vi.fn(), cancel: vi.fn(), resume: vi.fn() }
      ;(window as unknown as Record<string, unknown>).SpeechSynthesisUtterance = class {
        text: string
        onend: (() => void) | null = null
        onerror: (() => void) | null = null
        constructor(text: string) {
          this.text = text
        }
      }
      ;(window as unknown as Record<string, unknown>).speechSynthesis = engine
      return engine
    }

    it('offers no control where the browser cannot speak', () => {
      // jsdom has no engine, which is also every browser without one. A disabled
      // button would invite a click that can never work and explain nothing.
      renderCard()

      expect(screen.queryByRole('button', { name: /listen/i })).not.toBeInTheDocument()
    })

    it('reads the question aloud', () => {
      const engine = installEngine()
      renderCard()

      fireEvent.click(screen.getByRole('button', { name: 'Listen' }))

      expect(engine.speak).toHaveBeenCalledTimes(1)
    })

    it('offers to stop once it is reading', () => {
      // The label carries the state, so it has to change.
      installEngine()
      renderCard()

      fireEvent.click(screen.getByRole('button', { name: 'Listen' }))

      expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()
    })

    it('keeps the question on screen as text', () => {
      // Audio *and* text, not audio instead of it. Someone reading along, or
      // re-reading a clause they missed, needs the words there.
      installEngine()
      renderCard()

      fireEvent.click(screen.getByRole('button', { name: 'Listen' }))

      expect(screen.getByText(/how would you migrate a ledger/i)).toBeInTheDocument()
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
