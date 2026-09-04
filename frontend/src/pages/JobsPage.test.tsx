import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/services/apiClient'
import { jobService } from '@/services/jobService'
import type { JobSummary } from '@/types/job'
import { JobsPage } from './JobsPage'

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
    salary_min: '2800000.00',
    salary_max: '4500000.00',
    salary_currency: 'INR',
    salary_period: 'YEARLY',
    posted_at: null,
    created_at: '2026-09-03T00:00:00Z',
    skill_count: 7,
    ...overrides,
  }
}

function mockList(items: JobSummary[], total = items.length) {
  return vi
    .spyOn(jobService, 'list')
    .mockResolvedValue({ items, total, limit: 20, offset: 0 })
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <JobsPage />
    </MemoryRouter>,
  )

describe('JobsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('lists jobs with the facts the posting stated', async () => {
    mockList([jobFixture()])
    renderPage()

    const card = within(await screen.findByRole('listitem'))
    expect(card.getByRole('link', { name: 'Senior Data Engineer' })).toBeInTheDocument()
    expect(card.getByText(/Zeta Payments/)).toBeInTheDocument()
    expect(card.getByText(/Hybrid/)).toBeInTheDocument()
    expect(card.getByText(/4–7 years/)).toBeInTheDocument()
    // Compact notation: 2,800,000–4,500,000 is unreadable at a glance.
    expect(card.getByText(/INR 2\.8M – 4\.5M\/yr/)).toBeInTheDocument()
  })

  it('shows no salary when the posting stated none', async () => {
    // Never "competitive" — that would be the interface inventing a claim the
    // employer never made.
    mockList([
      jobFixture({ salary_min: null, salary_max: null, salary_currency: null, salary_period: null }),
    ])
    renderPage()

    await screen.findByRole('listitem')
    expect(screen.queryByText(/\/yr/)).not.toBeInTheDocument()
  })

  it('offers a way in when the corpus is empty', async () => {
    mockList([])
    renderPage()

    expect(await screen.findByText('No jobs yet.')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Add a job' }).length).toBeGreaterThan(0)
  })

  it('distinguishes an empty corpus from an empty filter result', async () => {
    // "No jobs yet" when the user has filtered to nothing would send them off
    // to paste a posting they already have.
    const user = userEvent.setup()
    mockList([])
    renderPage()
    await screen.findByText('No jobs yet.')

    await user.selectOptions(screen.getByLabelText('Work mode'), 'REMOTE')

    expect(await screen.findByText('No jobs match those filters.')).toBeInTheDocument()
  })

  it('sends the selected filters', async () => {
    const user = userEvent.setup()
    const list = mockList([jobFixture()])
    renderPage()
    await screen.findByRole('listitem')

    // Employment type rather than work mode: the subject is "a dropdown
    // selection reaches jobService.list", and work mode is already covered by
    // two other tests here.
    await user.selectOptions(screen.getByLabelText('Employment type'), 'FULL_TIME')

    await waitFor(() =>
      expect(list).toHaveBeenCalledWith(expect.objectContaining({ employment_type: 'FULL_TIME' })),
    )
  })

  describe('years of experience', () => {
    /**
     * These prove what is *requested*. The filtering itself is server-side and
     * is proven in backend/tests/api/test_jobs.py, which is also the only thing
     * pinning the parameter name — service.list_jobs(**filters: object) erases
     * types, so a typo would pass mypy and satisfy a spy like this one.
     */

    async function pick(user: ReturnType<typeof userEvent.setup>, option: string) {
      await user.click(screen.getByLabelText('Your experience'))
      await user.click(screen.getByRole('option', { name: option }))
    }

    it('sends the selection as a number', async () => {
      const user = userEvent.setup()
      const list = mockList([jobFixture()])
      renderPage()
      await screen.findByRole('listitem')

      await pick(user, '5+ years')

      await waitFor(() =>
        expect(list).toHaveBeenCalledWith(expect.objectContaining({ years_experience: 5 })),
      )
    })

    it('filters the options as you type, without firing a request', async () => {
      // The reason this is a Combobox rather than a native select. Nothing is
      // sent until an option is committed, which is also why the free-text
      // version's debounce is gone.
      const user = userEvent.setup()
      const list = mockList([jobFixture()])
      renderPage()
      await screen.findByRole('listitem')
      list.mockClear()

      await user.type(screen.getByLabelText('Your experience'), '1')

      // "1" matches both, in authored order.
      expect(screen.getByRole('option', { name: '1+ year' })).toBeInTheDocument()
      expect(screen.getByRole('option', { name: '10+ years' })).toBeInTheDocument()
      expect(list).not.toHaveBeenCalled()

      await user.keyboard('{Enter}')

      await waitFor(() =>
        expect(list).toHaveBeenCalledWith(expect.objectContaining({ years_experience: 1 })),
      )
    })

    it('treats zero as a filter, not as no filter', async () => {
      // Number('0') is falsy, so a check written on the converted value would
      // drop it — from the request, and from hasFilters, which decides whether
      // the empty state offers to add a job or to widen the search.
      const user = userEvent.setup()
      const list = mockList([])
      renderPage()
      await screen.findByText('No jobs yet.')

      await pick(user, '0+ years')

      await waitFor(() =>
        expect(list).toHaveBeenCalledWith(expect.objectContaining({ years_experience: 0 })),
      )
      expect(await screen.findByText('No jobs match those filters.')).toBeInTheDocument()
    })

    it('clears back to no filter', async () => {
      // The Combobox has no "Any" row, unlike the native selects beside it, so
      // the clear button is the only way back.
      const user = userEvent.setup()
      const list = mockList([])
      renderPage()
      await screen.findByText('No jobs yet.')

      await pick(user, '5+ years')
      await screen.findByText('No jobs match those filters.')

      await user.click(screen.getByRole('button', { name: 'Clear Your experience' }))

      await waitFor(() => {
        const sent = list.mock.calls.at(-1)?.[0]
        expect(sent).not.toHaveProperty('years_experience')
      })
      expect(await screen.findByText('No jobs yet.')).toBeInTheDocument()
    })
  })

  it('debounces the search rather than firing per keystroke', async () => {
    const user = userEvent.setup()
    const list = mockList([jobFixture()])
    renderPage()
    await screen.findByRole('listitem')
    list.mockClear()

    await user.type(screen.getByLabelText('Search'), 'data')

    await waitFor(() => expect(list).toHaveBeenCalledWith(expect.objectContaining({ q: 'data' })))
    // One request for the settled term, not one per character.
    expect(list).toHaveBeenCalledTimes(1)
  })

  it('returns to the first page when a filter changes', async () => {
    // Narrowing a search while on page three otherwise shows an empty list
    // that reads as "no results".
    const user = userEvent.setup()
    const list = mockList([jobFixture()], 50)
    renderPage()
    await screen.findByRole('listitem')

    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(list).toHaveBeenCalledWith(expect.objectContaining({ offset: 20 })))

    await user.selectOptions(screen.getByLabelText('Work mode'), 'REMOTE')

    await waitFor(() =>
      expect(list).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 0, work_mode: 'REMOTE' }),
      ),
    )

    // The experience filter is the third site that reads the selection — after
    // the request itself and hasFilters.
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(list).toHaveBeenCalledWith(expect.objectContaining({ offset: 20 })))

    await user.click(screen.getByLabelText('Your experience'))
    await user.click(screen.getByRole('option', { name: '5+ years' }))

    await waitFor(() =>
      expect(list).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 0, years_experience: 5 }),
      ),
    )
  })

  it('hides pagination when everything fits on one page', async () => {
    mockList([jobFixture()], 1)
    renderPage()

    await screen.findByRole('listitem')
    expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument()
  })

  it('reports a failed load and recovers', async () => {
    const user = userEvent.setup()
    const list = vi
      .spyOn(jobService, 'list')
      .mockRejectedValueOnce(new ApiError(500, 'INTERNAL_ERROR', 'Something broke.'))
      .mockResolvedValue({ items: [jobFixture()], total: 1, limit: 20, offset: 0 })
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('Something broke.')
    // Not an empty state: the corpus is not known to be empty.
    expect(screen.queryByText('No jobs yet.')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByRole('listitem')).toBeInTheDocument()
    expect(list).toHaveBeenCalledTimes(2)
  })
})
