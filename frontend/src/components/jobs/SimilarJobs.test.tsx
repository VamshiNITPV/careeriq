import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { jobService } from '@/services/jobService'
import type { JobSummary, SimilarJobsResponse } from '@/types/job'
import { SimilarJobs } from './SimilarJobs'

function jobFixture(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    id: 'j2',
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
    match_score: null,
    ...overrides,
  }
}

function response(overrides: Partial<SimilarJobsResponse> = {}): SimilarJobsResponse {
  return {
    items: [{ job: jobFixture(), similarity: 0.71 }],
    availability: 'READY',
    limit: 6,
    model_name: 'fake-hashing-trick',
    model_version: 'v1',
    ...overrides,
  }
}

const renderSection = () =>
  render(
    <MemoryRouter>
      <SimilarJobs jobId="j1" />
    </MemoryRouter>,
  )

describe('SimilarJobs', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('lists neighbours as ordinary job cards', async () => {
    // The same card as the browse list, which is why the endpoint returns a
    // full summary: the bookmark, the tags and the posting age come free.
    vi.spyOn(jobService, 'similar').mockResolvedValue(response())

    renderSection()

    expect(await screen.findByRole('heading', { name: 'Similar jobs' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Backend Python Developer' })).toBeInTheDocument()
  })

  it('never prints the similarity number', async () => {
    /*
     * The API returns one for debugging, but raw cosine on this model needs
     * rescaling before it means anything, and that rescaling is part of the
     * scoring step. An unrescaled 0.71 on a card would look like a percentage
     * and would not be one.
     */
    vi.spyOn(jobService, 'similar').mockResolvedValue(response())

    renderSection()
    await screen.findByRole('heading', { name: 'Similar jobs' })

    expect(screen.queryByText(/0\.71|71\s*%/)).not.toBeInTheDocument()
  })

  it('renders nothing at all when the request fails', async () => {
    // A side section must not put an error box on a job someone is reading, and
    // there is nothing they could do about it anyway.
    vi.spyOn(jobService, 'similar').mockRejectedValue(new Error('offline'))

    const { container } = renderSection()

    await waitFor(() => expect(jobService.similar).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when embeddings are switched off', async () => {
    // The default state of the app. A heading explaining that a feature the
    // user never asked for is disabled is pure noise.
    vi.spyOn(jobService, 'similar').mockResolvedValue(
      response({ items: [], availability: 'DISABLED', model_name: null, model_version: null }),
    )

    const { container } = renderSection()

    await waitFor(() => expect(jobService.similar).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when the comparison found nothing close enough', async () => {
    // READY with no items is a real answer, but "Similar jobs (0)" is noise.
    vi.spyOn(jobService, 'similar').mockResolvedValue(response({ items: [] }))

    const { container } = renderSection()

    await waitFor(() => expect(jobService.similar).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('says so plainly when this posting has not been indexed yet', async () => {
    // Not a spinner: nothing is in flight from the reader's point of view, and
    // a spinner that never resolves is worse than a sentence.
    vi.spyOn(jobService, 'similar').mockResolvedValue(
      response({ items: [], availability: 'PENDING' }),
    )

    renderSection()

    expect(await screen.findByText(/haven't indexed this posting yet/)).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
