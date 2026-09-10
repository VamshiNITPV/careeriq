import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { applicationService } from '@/services/applicationService'
import type { ApplicationListItem } from '@/types/application'
import { SavedJobs } from './SavedJobs'

function item(overrides: Partial<ApplicationListItem> = {}): ApplicationListItem {
  const status = overrides.status ?? 'SAVED'
  return {
    id: 'a1',
    job_id: 'j1',
    status,
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
          job: { ...item().job, id: 'j2', title: 'Backend Engineer' },
        }),
      ],
      total: 2,
    })
    renderSaved()

    await screen.findByRole('heading', { name: 'Saved' })
    expect(within(section('Saved')).getByText('Senior Data Engineer')).toBeInTheDocument()
    expect(within(section('Applications')).getByText('Backend Engineer')).toBeInTheDocument()
    // Disjoint: an applied job in both would make "Saved" a to-do list that
    // never empties.
    expect(within(section('Saved')).queryByText('Backend Engineer')).not.toBeInTheDocument()
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
    const user = userEvent.setup()
    const list = vi.spyOn(applicationService, 'list').mockResolvedValue({
      items: [item({ status: 'APPLIED' })],
      total: 1,
    })
    vi.spyOn(applicationService, 'remove').mockResolvedValue(undefined)
    renderSaved()

    await screen.findByText('Senior Data Engineer')
    expect(within(section('Applications')).getByText('Senior Data Engineer')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Remove Senior Data Engineer from saved/ }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(screen.queryByText('Senior Data Engineer')).not.toBeInTheDocument())
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
