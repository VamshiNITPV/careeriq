import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { jobService } from '@/services/jobService'
import type { JobSummary, RecommendationsResponse } from '@/types/job'
import { RecommendationsPage } from './RecommendationsPage'

function jobFixture(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    id: 'j1',
    title: 'Backend Python Developer',
    company: { id: 'c1', name: 'Acme', website: null, industry: null },
    location: 'Bengaluru, India',
    country_code: 'IN',
    work_mode: 'HYBRID',
    employment_type: 'FULL_TIME',
    experience_level: 'MID',
    min_years_experience: '4.0',
    max_years_experience: null,
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    salary_period: null,
    posted_at: null,
    created_at: '2026-09-03T00:00:00Z',
    skill_count: 4,
    application: null,
    ...overrides,
  }
}

function pageOf(ids: string[], nextCursor: string | null): RecommendationsResponse {
  return {
    items: ids.map((id) => ({
      job: jobFixture({ id, title: `Job ${id}` }),
      score: '68.4',
      breakdown: [],
      scored_weight: '0.60',
      skills: { matched: [], partial: [], missing: [] },
    })),
    availability: 'READY',
    next_cursor: nextCursor,
    limit: 10,
    considered: 200,
    ranking_version: 'v1-hand-tuned',
    resume_version_id: 'v1',
    computed_at: '2026-09-09T10:00:00Z',
  }
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <RecommendationsPage />
    </MemoryRouter>,
  )

describe('RecommendationsPage', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('lists the ranking with each job’s score', async () => {
    vi.spyOn(jobService, 'recommendations').mockResolvedValue(pageOf(['a', 'b'], null))

    renderPage()

    expect(await screen.findByText('Job a')).toBeInTheDocument()
    expect(screen.getAllByText(/68\.4 \/ 100/)).toHaveLength(2)
  })

  it('hides applied jobs by default, and stops when asked', async () => {
    /*
     * `exclude_applied` defaults to true server-side, so the common request
     * omits it — asserted on the call, because sending it either way would still
     * look correct on screen while making every URL noisier.
     */
    const fetch = vi.spyOn(jobService, 'recommendations').mockResolvedValue(pageOf(['a'], null))

    renderPage()
    await screen.findByText('Job a')
    expect(fetch).toHaveBeenLastCalledWith({ limit: 10, excludeApplied: true })

    await userEvent.click(screen.getByRole('checkbox', { name: /applied/i }))

    await waitFor(() =>
      expect(fetch).toHaveBeenLastCalledWith({ limit: 10, excludeApplied: false }),
    )
  })

  it('passes the minimum score through', async () => {
    const fetch = vi.spyOn(jobService, 'recommendations').mockResolvedValue(pageOf(['a'], null))

    renderPage()
    await screen.findByText('Job a')

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /minimum score/i }), '60')

    await waitFor(() =>
      expect(fetch).toHaveBeenLastCalledWith({ limit: 10, minScore: 60, excludeApplied: true }),
    )
  })

  it('restarts paging when a filter changes', async () => {
    /*
     * A filter change is a different ranking. Keeping the cursor would resume
     * partway through a list that no longer exists, which silently skips
     * whatever now sits at the top.
     */
    const fetch = vi
      .spyOn(jobService, 'recommendations')
      .mockResolvedValueOnce(pageOf(['a'], 'C2'))
      .mockResolvedValueOnce(pageOf(['b'], 'C3'))
      .mockResolvedValueOnce(pageOf(['c'], null))

    renderPage()
    await screen.findByText('Job a')
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('Job b')
    expect(screen.getByText('Page 2')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /minimum score/i }), '70')

    await screen.findByText('Job c')
    expect(fetch).toHaveBeenLastCalledWith({ limit: 10, minScore: 70, excludeApplied: true })
    expect(screen.getByText('Page 1')).toBeInTheDocument()
  })

  it('walks forward and back through pages', async () => {
    const fetch = vi
      .spyOn(jobService, 'recommendations')
      .mockResolvedValueOnce(pageOf(['a'], 'C2'))
      .mockResolvedValueOnce(pageOf(['b'], 'C3'))
      .mockResolvedValueOnce(pageOf(['a'], 'C2'))

    renderPage()
    await screen.findByText('Job a')
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('Job b')

    await userEvent.click(screen.getByRole('button', { name: 'Previous' }))

    await screen.findByText('Job a')
    // Page one is the request with no cursor, not a token that precedes the
    // first row.
    expect(fetch).toHaveBeenLastCalledWith({ limit: 10, excludeApplied: true })
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
  })

  it('says a failure is ours rather than implying nothing matches', async () => {
    /*
     * The dashboard panel stays silent on error because it sits beside content
     * the reader came for. A page whose entire purpose failed has to say so —
     * showing an empty list would read as "no job matches you", which is a very
     * different and much more discouraging claim.
     */
    vi.spyOn(jobService, 'recommendations').mockRejectedValue(new Error('offline'))

    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent(/problem on our side/i)
  })

  it('distinguishes an empty filter result from an empty ranking', async () => {
    vi.spyOn(jobService, 'recommendations').mockResolvedValue(pageOf([], null))

    renderPage()
    await screen.findByText(/matches closely enough/)

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /minimum score/i }), '70')

    // With a filter applied, "nothing matches you" would be wrong — the reader
    // set a threshold and can lower it.
    expect(await screen.findByText(/No jobs scored 70 or above/)).toBeInTheDocument()
  })

  it('asks for a resume instead of showing an empty ranking', async () => {
    vi.spyOn(jobService, 'recommendations').mockResolvedValue({
      ...pageOf([], null),
      availability: 'NO_RESUME',
      considered: 0,
    })

    renderPage()

    expect(await screen.findByRole('link', { name: 'Upload a resume' })).toHaveAttribute(
      'href',
      '/resume',
    )
  })
})
