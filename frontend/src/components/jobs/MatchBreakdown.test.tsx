import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { jobService } from '@/services/jobService'
import type { MatchDimension, MatchResponse } from '@/types/job'
import { MatchBreakdown } from './MatchBreakdown'

const DIMENSIONS: MatchDimension[] = [
  {
    dimension: 'semantic',
    score: '0.7100',
    weight: '0.35',
    contribution: '24.9',
    status: 'SCORED',
    reason: 'Your resume clearly overlaps with this posting.',
  },
  {
    dimension: 'skill',
    score: '0.8000',
    weight: '0.25',
    contribution: '20.0',
    status: 'SCORED',
    reason: 'Of the 5 skills this role asks for, you have Python and FastAPI.',
  },
  {
    dimension: 'experience',
    score: '0.5000',
    weight: '0.15',
    contribution: '7.5',
    status: 'NEEDS_PROFILE',
    reason: "We don't know how long you've been working, so this counts as neutral.",
  },
  {
    dimension: 'education',
    score: '1.0000',
    weight: '0.10',
    contribution: '10.0',
    status: 'NOT_STATED',
    reason: "This role doesn't state an education requirement.",
  },
  {
    dimension: 'location',
    score: '0.5000',
    weight: '0.10',
    contribution: '5.0',
    status: 'NEEDS_DATA',
    reason: "This posting doesn't say where the role is based, so this counts as neutral.",
  },
  {
    dimension: 'salary',
    score: '0.5000',
    weight: '0.05',
    contribution: '2.5',
    status: 'NOT_STATED',
    reason: "This posting doesn't list a salary, so this counts as neutral.",
  },
]

function response(overrides: Partial<MatchResponse> = {}): MatchResponse {
  return {
    job_id: 'j1',
    availability: 'READY',
    overall_score: '69.9',
    breakdown: DIMENSIONS,
    scored_weight: '0.60',
    skills: { matched: [], partial: [], missing: [] },
    ranking_version: 'v1-hand-tuned',
    resume_version_id: 'v1',
    computed_at: '2026-09-09T10:00:00Z',
    ...overrides,
  }
}

const renderPanel = () =>
  render(
    <MemoryRouter>
      <MatchBreakdown jobId="j1" />
    </MemoryRouter>,
  )

describe('MatchBreakdown', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('shows the score with every dimension that produced it', async () => {
    vi.spyOn(jobService, 'match').mockResolvedValue(response())

    renderPanel()

    expect(await screen.findByRole('heading', { name: 'How you match' })).toBeInTheDocument()
    expect(screen.getByText('69.9')).toBeInTheDocument()
    for (const label of ['Role fit', 'Skills', 'Experience', 'Education', 'Location', 'Salary']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('prints every contribution, including the ones that measured nothing', async () => {
    /*
     * Six visible numbers that add to the total is US-4.1 AC2 made checkable by
     * eye. Hiding the four neutral rows' contributions would leave a reader
     * unable to reproduce the score from what is on screen — which is the one
     * thing the payload guarantees.
     */
    vi.spyOn(jobService, 'match').mockResolvedValue(response())

    renderPanel()
    await screen.findByRole('heading', { name: 'How you match' })

    const shown = DIMENSIONS.map((row) => Number(row.contribution))
    for (const value of DIMENSIONS) {
      expect(screen.getByText(value.contribution)).toBeInTheDocument()
    }
    expect(shown.reduce((a, b) => a + b, 0)).toBeCloseTo(69.9, 5)
  })

  it('says out loud how much of the formula was informed', async () => {
    // The number is never alone. Without this sentence a 69.9 that four neutral
    // dimensions helped produce claims a confidence the data does not support.
    vi.spyOn(jobService, 'match').mockResolvedValue(response())

    renderPanel()

    expect(await screen.findByText(/60% of what we compare/)).toBeInTheDocument()
  })

  it('draws a bar only where something was actually measured', async () => {
    /*
     * A half-filled bar at 0.5 is a picture of a mediocre result, and that is a
     * lie: we did not measure mediocre, we measured nothing.
     */
    vi.spyOn(jobService, 'match').mockResolvedValue(response())

    renderPanel()
    await screen.findByRole('heading', { name: 'How you match' })

    const bars = screen.getAllByRole('meter')
    expect(bars.map((bar) => bar.getAttribute('aria-label'))).toEqual(['Role fit', 'Skills'])
  })

  it('offers a remedy for a profile gap and never for a gap in the posting', async () => {
    /*
     * The distinction the four-state status exists for. "This posting doesn't
     * say where it is" must not render a button telling the reader to fix their
     * profile — that blames them for an employer's omission.
     */
    vi.spyOn(jobService, 'match').mockResolvedValue(response())

    renderPanel()
    await screen.findByRole('heading', { name: 'How you match' })

    const experience = screen.getByText(/how long you've been working/).closest('li')!
    const remedy = within(experience).getByRole('link', { name: /update your profile/i })
    expect(remedy).toBeVisible()
    // The destination, not just the presence. A link that renders and goes
    // nowhere passes every "is it there" assertion — which is exactly how the
    // upload button below shipped pointing at a route that does not exist.
    expect(remedy).toHaveAttribute('href', '/profile')

    const location = screen.getByText(/where the role is based/).closest('li')!
    expect(within(location).queryByRole('link')).not.toBeInTheDocument()
  })

  it('asks for a resume instead of scoring someone it has never seen', async () => {
    // Rendering "20 / 100" for a new account is not a low score, it is a
    // fabricated judgement — and the upload is the most useful thing on the page.
    vi.spyOn(jobService, 'match').mockResolvedValue(
      response({ availability: 'NO_RESUME', overall_score: null, breakdown: [] }),
    )

    renderPanel()

    const upload = await screen.findByRole('link', { name: 'Upload a resume' })
    // `/resume`, singular — `/resumes` falls through to NotFoundPage, which is
    // how this shipped in 6.2 with a green test that only checked the link
    // rendered.
    expect(upload).toHaveAttribute('href', '/resume')
    expect(screen.queryByRole('meter')).not.toBeInTheDocument()
    expect(screen.queryByText('20')).not.toBeInTheDocument()
  })

  it('still shows a complete breakdown when the semantic dimension could not run', async () => {
    // The common case today. PARTIAL is a real answer, not a failure — throwing
    // away five dimensions that did run would be the worse outcome.
    vi.spyOn(jobService, 'match').mockResolvedValue(
      response({
        availability: 'PARTIAL',
        breakdown: DIMENSIONS.map((row) =>
          row.dimension === 'semantic'
            ? {
                ...row,
                score: '0.5000',
                contribution: '17.5',
                status: 'NEEDS_DATA' as const,
                reason: "We haven't compared this posting against your resume yet.",
              }
            : row,
        ),
      }),
    )

    renderPanel()
    await screen.findByRole('heading', { name: 'How you match' })

    expect(screen.getAllByRole('listitem')).toHaveLength(6)
    expect(screen.getAllByRole('meter')).toHaveLength(1)
  })

  it('renders nothing at all when the request fails', async () => {
    // A panel, not a page. The same rule SimilarJobs follows.
    vi.spyOn(jobService, 'match').mockRejectedValue(new Error('offline'))

    const { container } = renderPanel()

    await waitFor(() => expect(jobService.match).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})
