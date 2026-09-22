import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/services/apiClient'
import { applicationService } from '@/services/applicationService'
import type { ApplicationListItem, ApplicationStatus } from '@/types/application'
import type { JobSummary } from '@/types/job'
import { ApplicationBoard } from './ApplicationBoard'

function jobFixture(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    id: 'j1',
    title: 'Backend Engineer',
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

function item(overrides: Partial<ApplicationListItem> = {}): ApplicationListItem {
  const status = (overrides.status ?? 'APPLIED') as ApplicationStatus
  return {
    id: 'a1',
    job_id: 'j1',
    status,
    is_saved: true,
    applied_at: status === 'SAVED' ? null : '2026-09-10T00:00:00Z',
    created_at: '2026-09-03T00:00:00Z',
    job: jobFixture(),
    ...overrides,
  }
}

const renderBoard = () =>
  render(
    <MemoryRouter>
      <ApplicationBoard />
    </MemoryRouter>,
  )

describe('ApplicationBoard', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('groups applications under the stage they are in', async () => {
    vi.spyOn(applicationService, 'list').mockResolvedValue({
      items: [
        item({ id: 'a1', status: 'APPLIED', job: jobFixture({ title: 'Backend Engineer' }) }),
        item({
          id: 'a2',
          job_id: 'j2',
          status: 'INTERVIEW',
          job: jobFixture({ id: 'j2', title: 'Platform Engineer' }),
        }),
      ],
      total: 2,
    })

    renderBoard()

    // Headings, not just the rows: the grouping is the feature, and two rows
    // rendered flat would pass an assertion that only looked for the titles.
    expect(await screen.findByRole('heading', { name: /Applied/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Interview/ })).toBeInTheDocument()
  })

  it('does not render a heading for a stage with nothing in it', async () => {
    vi.spyOn(applicationService, 'list').mockResolvedValue({
      items: [item({ status: 'APPLIED' })],
      total: 1,
    })

    renderBoard()

    await screen.findByRole('heading', { name: /Applied/ })
    // A permanently visible empty "Rejected" heading is a discouraging thing to
    // put on somebody's job hunt in exchange for no information.
    expect(screen.queryByRole('heading', { name: /Rejected/ })).not.toBeInTheDocument()
  })

  it('sends the move and reloads from the server', async () => {
    const list = vi.spyOn(applicationService, 'list').mockResolvedValue({
      items: [item({ status: 'APPLIED' })],
      total: 1,
    })
    const change = vi
      .spyOn(applicationService, 'changeStatus')
      .mockResolvedValue({ ...item({ status: 'INTERVIEW' }) })

    renderBoard()
    await userEvent.click(await screen.findByRole('button', { name: /Move Backend Engineer/ }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Interview' }))

    await waitFor(() => expect(change).toHaveBeenCalledWith('a1', 'INTERVIEW'))
    // Refetched rather than patched locally: a transition can change more than
    // the row that moved — returning to SAVED clears applied_at server-side —
    // so the list is re-read rather than guessed at.
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2))
  })

  it('shows where the application can actually go when a move is refused', async () => {
    vi.spyOn(applicationService, 'list').mockResolvedValue({
      items: [item({ status: 'REJECTED' })],
      total: 1,
    })
    vi.spyOn(applicationService, 'changeStatus').mockRejectedValue(
      new ApiError(409, 'INVALID_STATUS_TRANSITION', 'An application cannot go from REJECTED to OFFER.', {
        allowed: ['APPLIED'],
      }),
    )

    renderBoard()
    await userEvent.click(await screen.findByRole('button', { name: /Move Backend Engineer/ }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Offer' }))

    // The server's own answer. Collapsing this into "something went wrong"
    // would throw away the one fact that tells the user what to do instead.
    expect(await screen.findByText(/cannot go from REJECTED to OFFER/)).toBeInTheDocument()
    expect(screen.getByText(/You can move it to: Applied/)).toBeInTheDocument()
  })

  it('says so plainly when there is nothing to show', async () => {
    vi.spyOn(applicationService, 'list').mockResolvedValue({ items: [], total: 0 })

    renderBoard()

    expect(await screen.findByText(/Nothing here yet/)).toBeInTheDocument()
  })

  it('reports a failed load rather than rendering an empty funnel', async () => {
    vi.spyOn(applicationService, 'list').mockRejectedValue(new Error('network'))

    renderBoard()

    // "You have no applications" and "we could not reach the server" must never
    // look the same — one is a fact about the user, the other about us.
    expect(await screen.findByText(/couldn't load your applications/i)).toBeInTheDocument()
    expect(screen.queryByText(/Nothing here yet/)).not.toBeInTheDocument()
  })
  it('names the stage in each card heading, not just the count', async () => {
    vi.spyOn(applicationService, 'list').mockResolvedValue({
      items: [item({ status: 'APPLIED' })],
      total: 1,
    })

    renderBoard()

    // The stage name has to be inside the heading. With the pill beside it
    // instead, every card's accessible name was "1 job" and a screen reader
    // never said which stage — the one piece of information this page carries.
    const heading = await screen.findByRole('heading', { name: /Applied/ })
    expect(heading).toHaveAccessibleName(expect.stringContaining('Applied'))
  })

  it('draws a meter per stage with the counts it actually has', async () => {
    vi.spyOn(applicationService, 'list').mockResolvedValue({
      items: [
        item({ id: 'a1', status: 'APPLIED' }),
        item({ id: 'a2', job_id: 'j2', status: 'APPLIED' }),
        item({ id: 'a3', job_id: 'j3', status: 'INTERVIEW' }),
      ],
      total: 3,
    })

    renderBoard()

    const applied = await screen.findByRole('meter', { name: 'Applied: 2' })
    expect(applied).toHaveAttribute('aria-valuenow', '2')
    // Scaled against the busiest stage, not the total: one application per
    // stage would otherwise draw five stripes too thin to see.
    expect(applied).toHaveAttribute('aria-valuemax', '2')
    expect(screen.getByRole('meter', { name: 'Interview: 1' })).toHaveAttribute(
      'aria-valuenow',
      '1',
    )
  })

  it('offers a way in when there is nothing yet', async () => {
    vi.spyOn(applicationService, 'list').mockResolvedValue({ items: [], total: 0 })

    renderBoard()

    // Carried over from the Saved jobs page this screen replaced. An empty
    // state that only explains itself leaves the reader with nowhere to go.
    expect(await screen.findByRole('link', { name: /Browse jobs/ })).toHaveAttribute(
      'href',
      '/jobs',
    )
  })

  it('keeps the bookmark control on every row', async () => {
    vi.spyOn(applicationService, 'list').mockResolvedValue({
      items: [item({ status: 'APPLIED', is_saved: true })],
      total: 1,
    })

    renderBoard()

    // Also carried over. Deleting /saved-jobs without this would have removed
    // the only place to unsave a job.
    expect(
      await screen.findByRole('button', { name: /Remove Backend Engineer from saved/ }),
    ).toBeInTheDocument()
  })

  it('lets you return here from the job it links to', async () => {
    vi.spyOn(applicationService, 'list').mockResolvedValue({
      items: [item({ status: 'APPLIED' })],
      total: 1,
    })

    renderBoard()

    // The job page falls back to /jobs when this state is absent — silently,
    // and plausibly, since /jobs is a real page it might have come from.
    const link = await screen.findByRole('link', { name: 'Backend Engineer' })
    await userEvent.click(link)
    expect(link).toHaveAttribute('href', '/jobs/j1')
  })
})
