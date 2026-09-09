import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { jobService } from '@/services/jobService'
import type { JobSummary, RecommendationsResponse } from '@/types/job'
import { RecommendedJobs } from './RecommendedJobs'

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

function response(overrides: Partial<RecommendationsResponse> = {}): RecommendationsResponse {
  return {
    items: [
      {
        job: jobFixture(),
        score: '68.4',
        breakdown: [],
        scored_weight: '0.60',
        skills: { matched: [], partial: [], missing: [] },
      },
    ],
    availability: 'READY',
    next_cursor: null,
    limit: 5,
    considered: 200,
    ranking_version: 'v1-hand-tuned',
    resume_version_id: 'v1',
    computed_at: '2026-09-09T10:00:00Z',
    ...overrides,
  }
}

const renderSection = () =>
  render(
    <MemoryRouter>
      <RecommendedJobs />
    </MemoryRouter>,
  )

describe('RecommendedJobs', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('lists ranked jobs as ordinary job cards, with the score', async () => {
    vi.spyOn(jobService, 'recommendations').mockResolvedValue(response())

    renderSection()

    expect(await screen.findByRole('heading', { name: 'Recommended for you' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Backend Python Developer' })).toBeInTheDocument()
    expect(screen.getByText(/68\.4 \/ 100/)).toBeInTheDocument()
  })

  it('asks for a resume rather than showing an empty list', async () => {
    /*
     * The three empty states need three different answers. Collapsing them into
     * one "no matches" sends a user hunting for a problem that is not theirs.
     */
    vi.spyOn(jobService, 'recommendations').mockResolvedValue(
      response({ items: [], availability: 'NO_RESUME', considered: 0 }),
    )

    renderSection()

    const upload = await screen.findByRole('link', { name: 'Upload a resume' })
    expect(upload).toHaveAttribute('href', '/resume')
  })

  it('says indexing has not caught up rather than claiming nothing matched', async () => {
    vi.spyOn(jobService, 'recommendations').mockResolvedValue(
      response({ items: [], availability: 'PENDING', considered: 0 }),
    )

    renderSection()

    expect(await screen.findByText(/haven't finished reading your resume/)).toBeInTheDocument()
    // Not a spinner: nothing is in flight from the reader's point of view.
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('distinguishes a genuine empty result from the other two', async () => {
    vi.spyOn(jobService, 'recommendations').mockResolvedValue(
      response({ items: [], availability: 'READY', considered: 0 }),
    )

    renderSection()

    expect(await screen.findByText(/matches closely enough/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Upload a resume' })).not.toBeInTheDocument()
  })

  it('renders nothing at all when the request fails', async () => {
    // A dashboard panel, not a page. Same rule the other sections follow.
    vi.spyOn(jobService, 'recommendations').mockRejectedValue(new Error('offline'))

    const { container } = renderSection()

    await waitFor(() => expect(jobService.recommendations).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('does not put six breakdown rows on every card', async () => {
    /*
     * The full explanation lives on the job page. Ten cards times six rows is
     * not a summary, it is a wall — and the reader has not yet decided any of
     * these jobs is worth the time.
     */
    vi.spyOn(jobService, 'recommendations').mockResolvedValue(response())

    renderSection()
    await screen.findByRole('heading', { name: 'Recommended for you' })

    expect(screen.queryByRole('meter')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'see why' })).toHaveAttribute('href', '/jobs/j1')
  })
})
