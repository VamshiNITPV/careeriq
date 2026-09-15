import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { optimizationService } from '@/services/optimizationService'
import type { AnalysisResponse, Suggestion } from '@/types/optimization'

import { OptimizePage } from './OptimizePage'

function suggestion(overrides: Partial<Suggestion> = {}): Suggestion {
  return {
    id: 's1',
    position: 1,
    section: 'experience',
    original: 'Worked on the payments backend.',
    suggested: 'Built and maintained payment processing services.',
    rationale: 'The job emphasises payment systems.',
    grounded_in: ['Worked on the payments backend.'],
    decision: 'PENDING',
    decided_at: null,
    ...overrides,
  }
}

function analysis(overrides: Partial<AnalysisResponse> = {}): AnalysisResponse {
  return {
    analysis_id: 'a1',
    resume_version_id: 'v1',
    job_id: 'j1',
    status: 'COMPLETE',
    error: null,
    suggestions: [suggestion()],
    rejected_by_validator: 0,
    dropped_malformed: 0,
    completed_at: '2026-09-15T10:00:00Z',
    ...overrides,
  }
}

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/optimize/a1']}>
      <Routes>
        <Route path="/optimize/:analysisId" element={<OptimizePage />} />
      </Routes>
    </MemoryRouter>,
  )

describe('OptimizePage', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('shows the original and the rewrite together', async () => {
    /*
     * Showing only the suggestion would ask someone to approve a change they
     * cannot see. The comparison is the thing being reviewed.
     */
    vi.spyOn(optimizationService, 'read').mockResolvedValue(analysis())

    renderPage()

    expect(await screen.findByText('Worked on the payments backend.')).toBeInTheDocument()
    expect(
      screen.getByText('Built and maintained payment processing services.'),
    ).toBeInTheDocument()
  })

  it('does not repeat the original line as its own source', async () => {
    /*
     * A model usually cites the very line it is rewriting. Listing that under
     * "also based on" says nothing and buries the sources that do add
     * something — which is the only reason the section is worth showing.
     */
    vi.spyOn(optimizationService, 'read').mockResolvedValue(analysis())

    renderPage()
    await screen.findByText('Worked on the payments backend.')

    expect(screen.queryByText('Also based on')).not.toBeInTheDocument()
  })

  it('shows sources that add something beyond the original', async () => {
    vi.spyOn(optimizationService, 'read').mockResolvedValue(
      analysis({
        suggestions: [
          suggestion({
            grounded_in: ['Worked on the payments backend.', 'Skills: Python, Django'],
          }),
        ],
      }),
    )

    renderPage()

    expect(await screen.findByText('Also based on')).toBeInTheDocument()
    expect(screen.getByText('Skills: Python, Django')).toBeInTheDocument()
  })

  it('applies only the suggestions the reader chose', async () => {
    /*
     * US-6.1 AC1. Each one is a claim about the reader's own work, so nothing
     * is applied because it was merely offered.
     */
    const user = userEvent.setup()
    vi.spyOn(optimizationService, 'read').mockResolvedValue(
      analysis({
        suggestions: [suggestion(), suggestion({ id: 's2', position: 2 })],
      }),
    )
    const apply = vi
      .spyOn(optimizationService, 'apply')
      .mockResolvedValue({
        resume_version_id: 'v2',
        version_number: 2,
        applied: 1,
        rejected: 1,
        message: 'Created version 2 with 1 change.',
      })

    renderPage()
    const cards = await screen.findAllByRole('listitem')
    await user.click(within(cards[0]!).getByRole('button', { name: 'Use this' }))

    await user.click(screen.getByRole('button', { name: /Save as a new version/ }))

    await waitFor(() => expect(apply).toHaveBeenCalledWith('a1', ['s1']))
  })

  it('cannot be applied with nothing selected', async () => {
    // The server refuses it anyway; disabling says why before the round trip.
    vi.spyOn(optimizationService, 'read').mockResolvedValue(analysis())

    renderPage()

    expect(await screen.findByRole('button', { name: /Save as a new version/ })).toBeDisabled()
  })

  it('lets a choice be taken back', async () => {
    // Reviewing is not a one-way door. Clicking again clears the choice.
    const user = userEvent.setup()
    vi.spyOn(optimizationService, 'read').mockResolvedValue(analysis())

    renderPage()
    const use = await screen.findByRole('button', { name: 'Use this' })

    await user.click(use)
    expect(use).toHaveAttribute('aria-pressed', 'true')

    await user.click(use)
    expect(use).toHaveAttribute('aria-pressed', 'false')
  })

  it('says a new version was created and the original is untouched', async () => {
    /*
     * "New version" alone would leave someone wondering whether their upload
     * was overwritten, which is the single thing this feature must never do.
     */
    const user = userEvent.setup()
    vi.spyOn(optimizationService, 'read').mockResolvedValue(analysis())
    vi.spyOn(optimizationService, 'apply').mockResolvedValue({
      resume_version_id: 'v2',
      version_number: 2,
      applied: 1,
      rejected: 0,
      message: 'Created version 2 with 1 change.',
    })

    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Use this' }))
    await user.click(screen.getByRole('button', { name: /Save as a new version/ }))

    expect(await screen.findByText(/original resume is unchanged/i)).toBeInTheDocument()
  })

  it('reports how many were withheld for inventing something', async () => {
    /*
     * An unexplained short list invites the reader to assume the model had
     * nothing to say, when in fact something was caught (ADR-012).
     */
    vi.spyOn(optimizationService, 'read').mockResolvedValue(
      analysis({ rejected_by_validator: 2 }),
    )

    renderPage()

    expect(await screen.findByText(/2 further/)).toBeInTheDocument()
  })

  it('explains an empty list caused by the validator', async () => {
    // "No changes to suggest" alone would be misleading here: there were
    // changes, and they were withheld for a reason worth stating.
    vi.spyOn(optimizationService, 'read').mockResolvedValue(
      analysis({ suggestions: [], rejected_by_validator: 3 }),
    )

    renderPage()

    expect(await screen.findByText(/withheld 3/i)).toBeInTheDocument()
  })

  it('waits while the model is still working', async () => {
    vi.spyOn(optimizationService, 'read').mockResolvedValue(analysis({ status: 'RUNNING' }))

    renderPage()

    expect(await screen.findByText(/Reading your resume against this job/)).toBeInTheDocument()
  })

  it('shows the reason a failed analysis gives', async () => {
    /*
     * The server always sets one on failure. Replacing it with a generic
     * message would discard the only thing that tells the user whether to wait,
     * retry, or fix something.
     */
    vi.spyOn(optimizationService, 'read').mockResolvedValue(
      analysis({
        status: 'FAILED',
        suggestions: [],
        error: "We've hit today's limit for AI suggestions. Please try again later.",
      }),
    )

    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent(/today's limit/)
  })

  it('offers a way back to the job after a failure', async () => {
    /*
     * The reason is stored on the row, so reloading shows the same failure
     * forever. Without a way out the reader is stranded on a page that can
     * never改 change, having to work out for themselves that a new analysis has
     * to be started from the job.
     */
    vi.spyOn(optimizationService, 'read').mockResolvedValue(
      analysis({ status: 'FAILED', suggestions: [], error: 'Something went wrong.' }),
    )

    renderPage()

    expect(await screen.findByRole('link', { name: 'Go back to the job' })).toHaveAttribute(
      'href',
      '/jobs/j1',
    )
  })

  it('keeps the suggestions on screen when saving fails', async () => {
    // Losing the list would lose the review, and the reader would have to make
    // every decision again.
    const user = userEvent.setup()
    vi.spyOn(optimizationService, 'read').mockResolvedValue(analysis())
    vi.spyOn(optimizationService, 'apply').mockRejectedValue(new Error('offline'))

    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Use this' }))
    await user.click(screen.getByRole('button', { name: /Save as a new version/ }))

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('Worked on the payments backend.')).toBeInTheDocument()
  })

  it('says a failure to load is ours', async () => {
    vi.spyOn(optimizationService, 'read').mockRejectedValue(new Error('offline'))

    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent(/problem on our side/i)
  })
})
