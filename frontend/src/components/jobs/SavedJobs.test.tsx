import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { applicationService } from '@/services/applicationService'
import type { ApplicationListItem } from '@/types/application'
import { SavedJobs } from './SavedJobs'

/** The link state a navigation carried — what the job page's back link is built from. */
function StateProbe() {
  const location = useLocation()
  return <span aria-label="link state">{JSON.stringify(location.state)}</span>
}

function item(overrides: Partial<ApplicationListItem> = {}): ApplicationListItem {
  const status = overrides.status ?? 'SAVED'
  return {
    id: 'a1',
    job_id: 'j1',
    status,
    // Defaults to bookmarked, and independent of `status` — an override can set
    // either without implying the other, which is the point of the split.
    is_saved: overrides.is_saved ?? true,
    applied_at: status === 'APPLIED' ? '2026-09-04T09:00:00Z' : null,
    created_at: '2026-09-04T08:00:00Z',
    job: {
      id: 'j1',
      title: 'Senior Data Engineer',
      company: { id: 'c1', name: 'Zeta Payments', website: null, industry: null },
      match_score: null,
      location: 'Bengaluru, India',
      country_code: 'IN',
      work_mode: 'HYBRID',
      employment_type: 'FULL_TIME',
      experience_level: 'SENIOR',
      min_years_experience: null,
      max_years_experience: null,
      salary_min: null,
      salary_max: null,
      salary_currency: null,
      salary_period: null,
      posted_at: null,
      created_at: '2026-09-03T00:00:00Z',
      skill_count: 3,
      application: null,
    },
    ...overrides,
  }
}

const renderSaved = () =>
  render(
    <MemoryRouter>
      <SavedJobs />
    </MemoryRouter>,
  )

const section = (name: string) => screen.getByRole('heading', { name }).closest('section')!

describe('SavedJobs', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('sorts each entry into the right list', async () => {
    vi.spyOn(applicationService, 'list').mockResolvedValue({
      items: [
        item({ id: 'a1', job_id: 'j1' }),
        item({
          id: 'a2',
          job_id: 'j2',
          status: 'APPLIED',
          is_saved: false,
          job: { ...item().job, id: 'j2', title: 'Backend Engineer' },
        }),
      ],
      total: 2,
    })
    renderSaved()

    await screen.findByRole('heading', { name: 'Saved' })
    expect(within(section('Saved')).getByText('Senior Data Engineer')).toBeInTheDocument()
    expect(within(section('Applications')).getByText('Backend Engineer')).toBeInTheDocument()
    // Applied but never bookmarked, so it is not in Saved.
    expect(within(section('Saved')).queryByText('Backend Engineer')).not.toBeInTheDocument()
  })

  it('shows a job you bookmarked and applied to in both lists', async () => {
    /*
     * These lists were disjoint while a job could only be saved *or* applied.
     * They ask two different questions now, and a job you bookmarked and then
     * applied to is a true answer to both — filtering it out of Saved would hide
     * a bookmark the user set and never cleared.
     */
    vi.spyOn(applicationService, 'list').mockResolvedValue({
      items: [item({ status: 'APPLIED', is_saved: true })],
      total: 1,
    })
    renderSaved()

    await screen.findByRole('heading', { name: 'Saved' })
    expect(within(section('Saved')).getByText('Senior Data Engineer')).toBeInTheDocument()
    expect(within(section('Applications')).getByText('Senior Data Engineer')).toBeInTheDocument()
  })

  it('sends you back to the saved list, not to the job list', async () => {
    /*
     * The reported bug. This row's link passed no navigation state, so the job
     * page fell through to its `/jobs` default — reading "Back to jobs" and
     * going there, from a page that was neither.
     */
    const user = userEvent.setup()
    vi.spyOn(applicationService, 'list').mockResolvedValue({ items: [item()], total: 1 })

    render(
      <MemoryRouter initialEntries={['/saved-jobs']}>
        <Routes>
          <Route path="/saved-jobs" element={<SavedJobs />} />
          <Route path="/jobs/:jobId" element={<StateProbe />} />
        </Routes>
      </MemoryRouter>,
    )
    await screen.findByText('Senior Data Engineer')

    await user.click(screen.getByRole('link', { name: 'Senior Data Engineer' }))

    expect(await screen.findByLabelText('link state')).toHaveTextContent(
      JSON.stringify({ backTo: '/saved-jobs' }),
    )
  })

  it('offers a way in when nothing is saved', async () => {
    vi.spyOn(applicationService, 'list').mockResolvedValue({ items: [], total: 0 })
    renderSaved()

    expect(await screen.findByText(/Nothing saved yet/)).toBeInTheDocument()
    expect(screen.getByText(/Nothing marked applied yet/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'browsing' })).toBeInTheDocument()
  })

  it('reports a failed load rather than an empty list', async () => {
    // Telling someone they saved nothing when the request merely failed is a
    // lie they may act on by saving everything again.
    const user = userEvent.setup()
    const list = vi
      .spyOn(applicationService, 'list')
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue({ items: [item()], total: 1 })
    renderSaved()

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't load/i)
    expect(screen.queryByText(/Nothing saved yet/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('Senior Data Engineer')).toBeInTheDocument()
    expect(list).toHaveBeenCalledTimes(2)
  })

  it('moves a row between the lists without refetching', async () => {
    // Un-bookmarking an applied job takes it out of Saved and leaves it under
    // Applications. No confirmation: nothing is lost by it any more.
    const user = userEvent.setup()
    const list = vi.spyOn(applicationService, 'list').mockResolvedValue({
      items: [item({ status: 'APPLIED', is_saved: true })],
      total: 1,
    })
    vi.spyOn(applicationService, 'set').mockResolvedValue({
      ...item({ status: 'APPLIED', is_saved: false }),
    })
    renderSaved()

    await screen.findByRole('heading', { name: 'Saved' })
    expect(within(section('Saved')).getByText('Senior Data Engineer')).toBeInTheDocument()

    await user.click(
      within(section('Saved')).getByRole('button', {
        name: /Remove Senior Data Engineer from saved/,
      }),
    )

    await waitFor(() =>
      expect(within(section('Saved')).queryByText('Senior Data Engineer')).not.toBeInTheDocument(),
    )
    expect(within(section('Applications')).getByText('Senior Data Engineer')).toBeInTheDocument()
    // The list is derived from one request, so nothing had to be re-fetched.
    expect(list).toHaveBeenCalledTimes(1)
  })

  it('shows when each entry was saved or applied', async () => {
    vi.spyOn(applicationService, 'list').mockResolvedValue({
      items: [item({ status: 'APPLIED' })],
      total: 1,
    })
    renderSaved()

    expect(await screen.findByText(/^Applied /)).toBeInTheDocument()
  })
})
