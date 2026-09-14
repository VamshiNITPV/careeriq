import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { learningService } from '@/services/learningService'
import type { LearningPathResponse, LearningStep } from '@/types/learning'

import { LearningPathPage } from './LearningPathPage'

function step(overrides: Partial<LearningStep> = {}): LearningStep {
  return {
    position: 1,
    skill_id: 's1',
    name: 'Docker',
    severity: 'HIGH',
    estimated_hours: 20,
    outcome: 'Containerise a service and run it with compose.',
    after: [],
    completed: false,
    ...overrides,
  }
}

function response(overrides: Partial<LearningPathResponse> = {}): LearningPathResponse {
  return {
    steps: [step()],
    total_hours: 20,
    remaining_hours: 20,
    target_jobs: 68,
    target_roles: ['Data Engineer'],
    job_id: null,
    skipped_uncurated: 0,
    availability: 'READY',
    ...overrides,
  }
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <LearningPathPage />
    </MemoryRouter>,
  )

describe('LearningPathPage', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('shows each step with its outcome and estimate', async () => {
    vi.spyOn(learningService, 'path').mockResolvedValue(response())

    renderPage()

    expect(await screen.findByText(/1\. Docker/)).toBeInTheDocument()
    expect(
      screen.getByText('Containerise a service and run it with compose.'),
    ).toBeInTheDocument()
    expect(screen.getByText('~20h')).toBeInTheDocument()
  })

  it('says why a step waits for another', async () => {
    // The order has to be arguable rather than arbitrary — a reader who cannot
    // see the reason has no way to disagree with it.
    vi.spyOn(learningService, 'path').mockResolvedValue(
      response({
        steps: [step({ position: 2, skill_id: 's2', name: 'Kubernetes', after: ['Docker'] })],
      }),
    )

    renderPage()

    expect(await screen.findByText('after Docker')).toBeInTheDocument()
  })

  it('reports progress against the whole plan', async () => {
    /*
     * "180 of 677 hours" says something "180 hours" does not. Both numbers are
     * on the page for that reason.
     */
    vi.spyOn(learningService, 'path').mockResolvedValue(
      response({
        steps: [step({ completed: true }), step({ skill_id: 's2', name: 'Kubernetes' })],
        total_hours: 65,
        remaining_hours: 45,
      }),
    )

    renderPage()

    const summary = await screen.findByRole('status')
    expect(summary).toHaveTextContent('45')
    expect(summary).toHaveTextContent('65')
    expect(summary).toHaveTextContent('1 of 2 done')
  })

  it('keeps a finished step on the page rather than hiding it', async () => {
    // The list is a route being walked. Dropping the finished parts would remove
    // the only evidence of progress there is.
    vi.spyOn(learningService, 'path').mockResolvedValue(
      response({ steps: [step({ completed: true })] }),
    )

    renderPage()

    expect(await screen.findByText(/Docker/)).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /Mark Docker as done/ })).toBeChecked()
  })

  it('ticks a step off and reloads, because the order can move', async () => {
    /*
     * Finishing a prerequisite unblocks what follows, so the plan itself changes
     * — refreshing only the one row would leave the rest of the list stale.
     */
    const user = userEvent.setup()
    const path = vi
      .spyOn(learningService, 'path')
      .mockResolvedValue(response())
      .mockResolvedValueOnce(response())
    const setCompleted = vi
      .spyOn(learningService, 'setCompleted')
      .mockResolvedValue({ message: 'Marked as done.' })

    renderPage()
    await screen.findByText(/Docker/)

    await user.click(screen.getByRole('checkbox', { name: /Mark Docker as done/ }))

    await waitFor(() => expect(setCompleted).toHaveBeenCalledWith('s1', true))
    await waitFor(() => expect(path).toHaveBeenCalledTimes(2))
  })

  it('puts the tick back when the server refuses', async () => {
    // Showing a step ticked that the server never recorded is worse than showing
    // that nothing happened — the reader would rely on it.
    const user = userEvent.setup()
    vi.spyOn(learningService, 'path').mockResolvedValue(response())
    vi.spyOn(learningService, 'setCompleted').mockRejectedValue(new Error('offline'))

    renderPage()
    const box = await screen.findByRole('checkbox', { name: /Mark Docker as done/ })

    await user.click(box)

    await waitFor(() =>
      expect(screen.getByRole('checkbox', { name: /Mark Docker as done/ })).not.toBeChecked(),
    )
  })

  it('says when gaps were left out for want of guidance', async () => {
    // Reported rather than invented over: a plan silently shorter than the gap
    // list is one a reader would assume is complete.
    vi.spyOn(learningService, 'path').mockResolvedValue(response({ skipped_uncurated: 24 }))

    renderPage()

    expect(await screen.findByText(/24 other missing/)).toBeInTheDocument()
  })

  it('says a tick is not a claim on your profile', async () => {
    /*
     * Studying something and putting it on a resume are different assertions.
     * The page has to say so, because a checkbox implies more than it does.
     */
    vi.spyOn(learningService, 'path').mockResolvedValue(response())

    renderPage()

    expect(await screen.findByText(/does not add the skill to your profile/)).toBeInTheDocument()
  })

  it('asks for target roles rather than showing an empty plan', async () => {
    vi.spyOn(learningService, 'path').mockResolvedValue(
      response({ steps: [], availability: 'NO_TARGET', target_roles: [] }),
    )

    renderPage()

    expect(await screen.findByRole('link', { name: 'Set your target roles' })).toHaveAttribute(
      'href',
      '/profile',
    )
  })

  it('says a failure is ours rather than implying there is nothing to learn', async () => {
    vi.spyOn(learningService, 'path').mockRejectedValue(new Error('offline'))

    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent(/problem on our side/i)
  })
})
