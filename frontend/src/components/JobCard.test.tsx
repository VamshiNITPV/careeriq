import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { applicationService } from '@/services/applicationService'
import type { ApplicationRead } from '@/types/application'
import type { JobSummary } from '@/types/job'
import { JobCard } from './JobCard'

function jobFixture(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    id: 'j1',
    title: 'Senior Data Engineer',
    company: { id: 'c1', name: 'Zeta Payments', website: null, industry: null },
    location: 'Bengaluru, India',
    country_code: 'IN',
    work_mode: 'HYBRID',
    employment_type: 'FULL_TIME',
    experience_level: 'SENIOR',
    min_years_experience: '4.0',
    max_years_experience: '7.0',
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    salary_period: null,
    posted_at: null,
    created_at: '2026-09-03T00:00:00Z',
    skill_count: 3,
    application: null,
    ...overrides,
  }
}

function saved(status: 'SAVED' | 'APPLIED' = 'SAVED'): ApplicationRead {
  return {
    id: 'a1',
    job_id: 'j1',
    status,
    applied_at: status === 'APPLIED' ? '2026-09-04T09:00:00Z' : null,
    created_at: '2026-09-04T08:00:00Z',
  }
}

const renderCard = (job: JobSummary, onChange?: (a: ApplicationRead | null) => void) =>
  render(
    <MemoryRouter>
      <ul>
        <JobCard job={job} {...(onChange ? { onApplicationChange: onChange } : {})} />
      </ul>
    </MemoryRouter>,
  )

describe('JobCard', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('names the bookmark after the job it saves', () => {
    // Twenty cards of "Save this job" are indistinguishable to anyone arrowing
    // through them with a screen reader.
    renderCard(jobFixture())

    expect(
      screen.getByRole('button', { name: 'Save Senior Data Engineer' }),
    ).toBeInTheDocument()
  })

  it('says what tapping it will do once the job is saved', () => {
    renderCard(jobFixture({ application: saved() }))

    expect(
      screen.getByRole('button', { name: 'Remove Senior Data Engineer from saved' }),
    ).toBeInTheDocument()
  })

  it('marks a job you have applied to', () => {
    renderCard(jobFixture({ application: saved('APPLIED') }))

    expect(screen.getByText('Applied')).toBeInTheDocument()
  })

  it('says nothing about applying when you have not', () => {
    renderCard(jobFixture({ application: saved() }))

    expect(screen.queryByText('Applied')).not.toBeInTheDocument()
  })

  it('fills the bookmark before the server answers', async () => {
    // Optimistic on purpose: a spinner on a bookmark for a 200ms round trip
    // reads as broken, and the write is idempotent so guessing wrong is cheap.
    const user = userEvent.setup()
    let resolve: (value: ApplicationRead) => void = () => {}
    vi.spyOn(applicationService, 'set').mockReturnValue(
      new Promise<ApplicationRead>((r) => {
        resolve = r
      }),
    )
    renderCard(jobFixture())

    await user.click(screen.getByRole('button', { name: 'Save Senior Data Engineer' }))

    expect(
      screen.getByRole('button', { name: 'Remove Senior Data Engineer from saved' }),
    ).toBeInTheDocument()
    resolve(saved())
  })

  it('puts the bookmark back when the save fails', async () => {
    // Showing a saved job the server never saved is worse than showing the
    // failure — the user would rely on finding it later.
    const user = userEvent.setup()
    vi.spyOn(applicationService, 'set').mockRejectedValue(new Error('offline'))
    renderCard(jobFixture())

    await user.click(screen.getByRole('button', { name: 'Save Senior Data Engineer' }))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Save Senior Data Engineer' })).toBeInTheDocument(),
    )
    expect(screen.getByRole('alert')).toHaveTextContent(/Couldn't save/)
  })

  it('tells the list what changed, so nothing has to refetch', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    vi.spyOn(applicationService, 'set').mockResolvedValue(saved())
    renderCard(jobFixture(), onChange)

    await user.click(screen.getByRole('button', { name: 'Save Senior Data Engineer' }))

    await waitFor(() => expect(onChange).toHaveBeenCalledWith(saved()))
  })

  it('keeps the bookmark out of the stretched link', () => {
    /**
     * The title link's `after:absolute after:inset-0` covers the whole card and
     * carries no z-index, so the bookmark needs `relative z-10` or a tap on it
     * navigates instead of saving.
     *
     * This asserts the classes are present and nothing more. **jsdom has no
     * layout**, so the actual failure — a click landing on the wrong element —
     * is not observable here at all. Only a real browser catches that; this
     * test exists so a refactor that drops the classes is noticed.
     */
    renderCard(jobFixture())

    const wrapper = screen.getByRole('button', { name: 'Save Senior Data Engineer' }).parentElement!
      .parentElement!
    expect(wrapper).toHaveClass('relative', 'z-10')
  })
})
