import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type * as ReactRouter from 'react-router-dom'
import { interviewService } from '@/services/interviewService'
import type { InterviewSummary } from '@/types/interview'

import { InterviewsPage } from './InterviewsPage'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof ReactRouter>('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})

function summary(overrides: Partial<InterviewSummary> = {}): InterviewSummary {
  return {
    id: 'i1',
    target_role: 'Backend Engineer',
    status: 'IN_PROGRESS',
    questions_asked: 3,
    question_budget: 10,
    answered: 2,
    average_score: '0.720',
    created_at: '2026-09-23T10:00:00Z',
    ...overrides,
  }
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <InterviewsPage />
    </MemoryRouter>,
  )

describe('InterviewsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    navigate.mockReset()
  })

  it('lists the interviews you can go back to', async () => {
    // US-8.1 AC2 says an interview is resumable. Without a list that is only
    // true for somebody who kept the URL.
    vi.spyOn(interviewService, 'list').mockResolvedValue({
      items: [summary(), summary({ id: 'i2', target_role: 'AI Engineer' })],
      total: 2,
    })

    renderPage()

    expect(await screen.findByRole('link', { name: /Backend Engineer/ })).toHaveAttribute(
      'href',
      '/interviews/i1',
    )
    expect(screen.getByRole('link', { name: /AI Engineer/ })).toHaveAttribute(
      'href',
      '/interviews/i2',
    )
  })

  it('shows answered separately from the budget', async () => {
    // Asked and answered are not the same number: the last question sits
    // unanswered for as long as somebody is thinking about it.
    vi.spyOn(interviewService, 'list').mockResolvedValue({
      items: [summary({ answered: 2, questions_asked: 3 })],
      total: 1,
    })

    renderPage()

    expect(await screen.findByText(/2 of 10 answered/)).toBeInTheDocument()
    expect(screen.getByText(/one waiting for you/)).toBeInTheDocument()
  })

  it('shows a dash rather than a zero when nothing is marked', async () => {
    // A 0 would read as having done badly at an interview nobody has marked.
    vi.spyOn(interviewService, 'list').mockResolvedValue({
      items: [summary({ average_score: null, answered: 0 })],
      total: 1,
    })

    renderPage()

    await screen.findByText(/0 of 10 answered/)
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.queryByText('0.0')).not.toBeInTheDocument()
  })

  it('invites you to start one when there are none', async () => {
    vi.spyOn(interviewService, 'list').mockResolvedValue({ items: [], total: 0 })

    renderPage()

    expect(await screen.findByText(/nothing here yet/i)).toBeInTheDocument()
  })

  describe('starting one', () => {
    beforeEach(() => {
      vi.spyOn(interviewService, 'list').mockResolvedValue({ items: [], total: 0 })
    })

    it('sends the role and goes to the session', async () => {
      const user = userEvent.setup()
      const start = vi
        .spyOn(interviewService, 'start')
        .mockResolvedValue({ interview_id: 'new1', status: 'CREATED', poll_url: '/x' })

      renderPage()
      await user.type(
        await screen.findByRole('textbox', { name: /role you are preparing for/i }),
        'AI Engineer',
      )
      await user.click(screen.getByRole('button', { name: 'Start' }))

      await waitFor(() => expect(start).toHaveBeenCalledWith({ target_role: 'AI Engineer' }))
      expect(navigate).toHaveBeenCalledWith('/interviews/new1')
    })

    it('trims the role rather than starting an interview for a space', async () => {
      const user = userEvent.setup()
      const start = vi
        .spyOn(interviewService, 'start')
        .mockResolvedValue({ interview_id: 'new1', status: 'CREATED', poll_url: '/x' })

      renderPage()
      await user.type(
        await screen.findByRole('textbox', { name: /role you are preparing for/i }),
        '  AI Engineer  ',
      )
      await user.click(screen.getByRole('button', { name: 'Start' }))

      await waitFor(() => expect(start).toHaveBeenCalledWith({ target_role: 'AI Engineer' }))
    })

    it('asks for a role instead of sending an empty one', async () => {
      const user = userEvent.setup()
      const start = vi.spyOn(interviewService, 'start')

      renderPage()
      await screen.findByRole('button', { name: 'Start' })
      await user.click(screen.getByRole('button', { name: 'Start' }))

      expect(await screen.findByRole('alert')).toBeInTheDocument()
      expect(start).not.toHaveBeenCalled()
    })

    it('reports a failure instead of navigating nowhere', async () => {
      const user = userEvent.setup()
      vi.spyOn(interviewService, 'start').mockRejectedValue(new Error('no provider'))

      renderPage()
      await user.type(
        await screen.findByRole('textbox', { name: /role you are preparing for/i }),
        'AI Engineer',
      )
      await user.click(screen.getByRole('button', { name: 'Start' }))

      expect(await screen.findByRole('alert')).toBeInTheDocument()
      expect(navigate).not.toHaveBeenCalled()
    })
  })

  it('says so when the list cannot be loaded', async () => {
    vi.spyOn(interviewService, 'list').mockRejectedValue(new Error('down'))

    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't load your interviews/i)
  })
})
