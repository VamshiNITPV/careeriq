import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

/** A page of cards with distinct ids, so two pages are tellable apart. */
function pageOf(ids: string[], nextCursor: string | null): RecommendationsResponse {
  return response({
    items: ids.map((id) => ({
      job: jobFixture({ id, title: `Job ${id}` }),
      score: '60.0',
      breakdown: [],
      scored_weight: '0.60',
      skills: { matched: [], partial: [], missing: [] },
    })),
    next_cursor: nextCursor,
  })
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

describe('RecommendedJobs paging', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('offers both controls on the first page, with Previous disabled', async () => {
    /*
     * Both stay mounted at every boundary. Hiding the control the reader just
     * clicked drops focus to <body>, and a Next that appears only once a second
     * page exists reads as the interface changing shape for no visible reason.
     */
    vi.spyOn(jobService, 'recommendations').mockResolvedValue(pageOf(['a', 'b'], 'CURSOR_2'))

    renderSection()
    await screen.findByRole('heading', { name: 'Recommended for you' })

    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled()
    expect(screen.getByText('Page 1')).toBeInTheDocument()
  })

  it('disables Next when the server stops sending a cursor', async () => {
    // The end is discovered from next_cursor, never calculated from a total:
    // `considered` is the size of the recall set, not of the market.
    vi.spyOn(jobService, 'recommendations').mockResolvedValue(pageOf(['a'], null))

    renderSection()
    await screen.findByRole('heading', { name: 'Recommended for you' })

    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
  })

  it('asks for exactly the cursor the server just returned', async () => {
    /*
     * The failure this catches is silent: send the wrong cursor, or none, and
     * page two is page one again — which looks like the button doing nothing.
     */
    const fetch = vi
      .spyOn(jobService, 'recommendations')
      .mockResolvedValueOnce(pageOf(['a', 'b'], 'CURSOR_2'))
      .mockResolvedValueOnce(pageOf(['c', 'd'], null))

    renderSection()
    await screen.findByText('Job a')

    await userEvent.click(screen.getByRole('button', { name: 'Next' }))

    await screen.findByText('Job c')
    expect(fetch).toHaveBeenLastCalledWith({ limit: 5, cursor: 'CURSOR_2' })
    expect(screen.getByText('Page 2')).toBeInTheDocument()
    expect(screen.queryByText('Job a')).not.toBeInTheDocument()
  })

  it('walks back to an earlier page after three forward, not just one', async () => {
    /*
     * Three deep on purpose. A stack that remembers only the immediately
     * previous cursor passes a one-step test and then serves the wrong page the
     * moment someone goes further — which is the whole reason Previous is a
     * history rather than a single remembered token.
     */
    const fetch = vi
      .spyOn(jobService, 'recommendations')
      .mockResolvedValueOnce(pageOf(['a'], 'C2'))
      .mockResolvedValueOnce(pageOf(['b'], 'C3'))
      .mockResolvedValueOnce(pageOf(['c'], 'C4'))
      .mockResolvedValueOnce(pageOf(['b'], 'C3'))

    renderSection()
    await screen.findByText('Job a')

    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('Job b')
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('Job c')
    expect(screen.getByText('Page 3')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Previous' }))

    await screen.findByText('Job b')
    // C2 is the cursor stored for page two — not C3, which is what a one-step
    // memory would have replayed.
    expect(fetch).toHaveBeenLastCalledWith({ limit: 5, cursor: 'C2' })
    expect(screen.getByText('Page 2')).toBeInTheDocument()
  })

  it('returns to the first page with no cursor at all', async () => {
    // Page one is the request with no cursor. Sending a token that happens to
    // precede the first row would be a different query with the same answer
    // today and a subtly different one later.
    const fetch = vi
      .spyOn(jobService, 'recommendations')
      .mockResolvedValueOnce(pageOf(['a'], 'C2'))
      .mockResolvedValueOnce(pageOf(['b'], null))
      .mockResolvedValueOnce(pageOf(['a'], 'C2'))

    renderSection()
    await screen.findByText('Job a')
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('Job b')

    await userEvent.click(screen.getByRole('button', { name: 'Previous' }))

    await screen.findByText('Job a')
    expect(fetch).toHaveBeenLastCalledWith({ limit: 5 })
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
  })

  it('keeps the rows on screen when a page turn fails', async () => {
    /*
     * This panel sits above other dashboard content. Blanking it over a failure
     * the reader cannot act on would collapse the section and shift everything
     * under their pointer — worse than simply staying put.
     */
    vi.spyOn(jobService, 'recommendations')
      .mockResolvedValueOnce(pageOf(['a', 'b'], 'CURSOR_2'))
      .mockRejectedValueOnce(new Error('offline'))

    renderSection()
    await screen.findByText('Job a')

    await userEvent.click(screen.getByRole('button', { name: 'Next' }))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Next' })).not.toHaveAttribute(
        'aria-busy',
        'true',
      ),
    )
    expect(screen.getByText('Job a')).toBeInTheDocument()
    expect(screen.getByText('Page 1')).toBeInTheDocument()
  })

  it('offers no controls when there is nothing to page', async () => {
    for (const availability of ['NO_RESUME', 'PENDING'] as const) {
      vi.spyOn(jobService, 'recommendations').mockResolvedValue(
        response({ items: [], availability, considered: 0 }),
      )

      const { unmount } = renderSection()
      await screen.findByRole('heading', { name: 'Recommended for you' })

      expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Previous' })).not.toBeInTheDocument()
      unmount()
    }
  })
})

describe('RecommendedJobs paging, back and forth', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('goes forward again after going back, without losing its place', async () => {
    /*
     * A real user path the other tests miss: page deep, retreat, advance again,
     * retreat again. It is the sequence where `page` and the cursor array stop
     * moving in lockstep, so it is the one that would catch a `goPrevious`
     * written against the array's length instead of against `page`.
     */
    const fetch = vi
      .spyOn(jobService, 'recommendations')
      .mockResolvedValueOnce(pageOf(['a'], 'C2')) // page 1
      .mockResolvedValueOnce(pageOf(['b'], 'C3')) // page 2
      .mockResolvedValueOnce(pageOf(['c'], 'C4')) // page 3
      .mockResolvedValueOnce(pageOf(['b'], 'C3')) // back to page 2
      .mockResolvedValueOnce(pageOf(['c'], 'C4')) // forward to page 3 again
      .mockResolvedValueOnce(pageOf(['b'], 'C3')) // back to page 2 again

    renderSection()
    await screen.findByText('Job a')

    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('Job b')
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('Job c')

    await userEvent.click(screen.getByRole('button', { name: 'Previous' }))
    await screen.findByText('Job b')
    expect(screen.getByText('Page 2')).toBeInTheDocument()

    // Forward again from page 2 must use the cursor page 2's response carries,
    // not the one stored before the walk back.
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('Job c')
    expect(fetch).toHaveBeenLastCalledWith({ limit: 5, cursor: 'C3' })
    expect(screen.getByText('Page 3')).toBeInTheDocument()

    // And back once more still lands on page 2, which is the assertion the
    // stack has to keep earning.
    await userEvent.click(screen.getByRole('button', { name: 'Previous' }))
    await screen.findByText('Job b')
    expect(fetch).toHaveBeenLastCalledWith({ limit: 5, cursor: 'C2' })
    expect(screen.getByText('Page 2')).toBeInTheDocument()
  })
})
