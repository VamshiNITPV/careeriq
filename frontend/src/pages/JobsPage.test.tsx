import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
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
    application: null,
    ...overrides,
  }
}

function mockList(items: JobSummary[], total = items.length) {
  return vi
    .spyOn(jobService, 'list')
    .mockResolvedValue({ items, total, limit: 20, offset: 0 })
}

/**
 * The current URL, exposed through the accessibility tree.
 *
 * There is no data-testid convention in this suite, and the filters now live in
 * the URL — so the URL has to be assertable. Not <output>, which carries an
 * implicit role="status" that the "Showing 1-20 of 50" line already owns on
 * this page.
 */
function LocationProbe() {
  const location = useLocation()
  return <span aria-label="location">{`${location.pathname}${location.search}`}</span>
}

const currentUrl = () => screen.getByLabelText('location').textContent

/** The link state a navigation carried, for the same reason as LocationProbe. */
function StateProbe() {
  const location = useLocation()
  return <span aria-label="link state">{JSON.stringify(location.state)}</span>
}

/** A back button, so a test can prove what did and did not enter history. */
function BackButton() {
  const navigate = useNavigate()
  return <button onClick={() => navigate(-1)}>test-back</button>
}

// The explicit '/jobs' matters: MemoryRouter's own default is '/', which would
// make every probe assertion read "/?q=..." instead.
const renderPage = (initialEntry = '/jobs') =>
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <JobsPage />
      <LocationProbe />
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

  describe('posted within', () => {
    it('sends the chosen window as a number of days', async () => {
      const user = userEvent.setup()
      const list = mockList([jobFixture()])
      renderPage()
      await screen.findByRole('listitem')

      await user.selectOptions(screen.getByLabelText('Posted within'), '7')

      await waitFor(() =>
        expect(list).toHaveBeenCalledWith(expect.objectContaining({ posted_within_days: 7 })),
      )
    })

    it('sends nothing at all when the window is "Any time"', async () => {
      // An always-present default window would quietly hide the older half of
      // the corpus from anyone who never touched this control.
      const list = mockList([jobFixture()])
      renderPage()
      await screen.findByRole('listitem')

      expect(list.mock.calls[0]?.[0]).not.toHaveProperty('posted_within_days')
    })
  })

  describe('the URL holds the filters', () => {
    /**
     * The point of all this: leave /jobs for a job posting and come back, and
     * the filters and the page are still there. They live in the URL, so Back
     * restores them, a refresh survives, and a filtered list is a link that can
     * be shared.
     */

    it('restores every filter and the page from the URL', async () => {
      const list = mockList([jobFixture()], 50)
      renderPage(
        '/jobs?q=python&work_mode=REMOTE&employment_type=FULL_TIME' +
          '&years_experience=5&posted_within_days=7&offset=20',
      )
      await screen.findByRole('listitem')

      // The FIRST call, not the last. What matters is that no mount-time
      // effect fired an unfiltered page-one request before this one.
      expect(list.mock.calls[0]?.[0]).toEqual({
        q: 'python',
        work_mode: 'REMOTE',
        employment_type: 'FULL_TIME',
        years_experience: 5,
        posted_within_days: 7,
        limit: 20,
        offset: 20,
      })
    })

    it('shows the restored values in the controls', async () => {
      mockList([jobFixture()], 50)
      renderPage('/jobs?q=python&work_mode=REMOTE&years_experience=5')
      await screen.findByRole('listitem')

      // An empty search box sitting over a filtered list is the version of
      // this bug that looks like the filter is broken.
      expect(screen.getByLabelText('Search')).toHaveValue('python')
      expect(screen.getByLabelText('Work mode')).toHaveValue('REMOTE')
      expect(screen.getByLabelText('Your experience')).toHaveValue('5+ years')
    })

    it('writes a filter change to the URL', async () => {
      const user = userEvent.setup()
      mockList([jobFixture()])
      renderPage()
      await screen.findByRole('listitem')

      await user.selectOptions(screen.getByLabelText('Work mode'), 'REMOTE')

      await waitFor(() => expect(currentUrl()).toBe('/jobs?work_mode=REMOTE'))
    })

    it('writes the settled search term, not each keystroke', async () => {
      const user = userEvent.setup()
      mockList([jobFixture()])
      renderPage()
      await screen.findByRole('listitem')

      await user.type(screen.getByLabelText('Search'), 'data')

      await waitFor(() => expect(currentUrl()).toBe('/jobs?q=data'))
    })

    it('drops the page from the URL when a filter changes', async () => {
      const user = userEvent.setup()
      const list = mockList([jobFixture()], 50)
      renderPage('/jobs?work_mode=REMOTE&offset=20')
      await screen.findByRole('listitem')

      await user.selectOptions(screen.getByLabelText('Employment type'), 'FULL_TIME')

      await waitFor(() => expect(currentUrl()).toBe('/jobs?work_mode=REMOTE&employment_type=FULL_TIME'))
      expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }))
    })

    it('removes a cleared filter from the URL rather than leaving it blank', async () => {
      const user = userEvent.setup()
      const list = mockList([jobFixture()])
      renderPage('/jobs?years_experience=5')
      await screen.findByRole('listitem')

      await user.click(screen.getByRole('button', { name: 'Clear Your experience' }))

      // A blank still reads as "no filter", so the request would stay correct
      // while the address bar filled with ?years_experience=&work_mode= —
      // which is why this asserts the URL and not only the request.
      await waitFor(() => expect(currentUrl()).toBe('/jobs'))
      expect(list.mock.lastCall?.[0]).not.toHaveProperty('years_experience')
    })

    it('ignores filter values the URL made up', async () => {
      const list = mockList([])
      renderPage('/jobs?work_mode=BANANA&years_experience=99&posted_within_days=999&offset=-5')
      await screen.findByText('No jobs yet.')

      // Nothing invalid reaches the API, which would answer 422 for it.
      expect(list.mock.calls[0]?.[0]).toEqual({ limit: 20, offset: 0 })
      // And the empty state does not claim filters are active and send the
      // user off widening a search they never made.
      expect(screen.queryByText('No jobs match those filters.')).not.toBeInTheDocument()
    })

    it('snaps an off-grid offset onto a page boundary', async () => {
      const list = mockList([jobFixture()], 50)
      renderPage('/jobs?offset=37')
      await screen.findByRole('listitem')

      expect(list.mock.calls[0]?.[0]).toEqual({ limit: 20, offset: 20 })
    })

    it('keeps filter changes out of history, and puts pages in it', async () => {
      const user = userEvent.setup()
      mockList([jobFixture()], 50)
      render(
        <MemoryRouter initialEntries={['/dashboard', '/jobs']} initialIndex={1}>
          <JobsPage />
          <LocationProbe />
          <BackButton />
        </MemoryRouter>,
      )
      await screen.findByRole('listitem')

      // Two filter changes, both replacing: one Back leaves /jobs entirely.
      // Pushing here would mean ten searches make a Back button that never
      // escapes the page — and Back from a job would land on the
      // second-to-last filter state, which is this bug one step removed.
      await user.selectOptions(screen.getByLabelText('Work mode'), 'REMOTE')
      await waitFor(() => expect(currentUrl()).toBe('/jobs?work_mode=REMOTE'))
      await user.selectOptions(screen.getByLabelText('Employment type'), 'FULL_TIME')
      await waitFor(() => expect(currentUrl()).toContain('employment_type'))

      await user.click(screen.getByRole('button', { name: 'test-back' }))

      await waitFor(() => expect(currentUrl()).toBe('/dashboard'))
    })

    it('puts a page change in history', async () => {
      const user = userEvent.setup()
      mockList([jobFixture()], 50)
      render(
        <MemoryRouter initialEntries={['/jobs']}>
          <JobsPage />
          <LocationProbe />
          <BackButton />
        </MemoryRouter>,
      )
      await screen.findByRole('listitem')

      // A page is a real position in a list, and Back from page two should be
      // page one rather than leaving the list.
      await user.click(screen.getByRole('button', { name: 'Next' }))
      await waitFor(() => expect(currentUrl()).toBe('/jobs?offset=20'))

      await user.click(screen.getByRole('button', { name: 'test-back' }))

      await waitFor(() => expect(currentUrl()).toBe('/jobs'))
    })

    it('carries the list you were on into the job link', async () => {
      const user = userEvent.setup()
      mockList([jobFixture()], 50)
      render(
        <MemoryRouter initialEntries={['/jobs?work_mode=REMOTE&offset=20']}>
          <Routes>
            <Route path="/jobs" element={<JobsPage />} />
            <Route
              path="/jobs/:jobId"
              element={<StateProbe />}
            />
          </Routes>
        </MemoryRouter>,
      )
      await screen.findByRole('listitem')

      await user.click(screen.getByRole('link', { name: 'Senior Data Engineer' }))

      // What the detail page's "back to jobs" link is built from.
      expect(await screen.findByLabelText('link state')).toHaveTextContent(
        JSON.stringify({ backTo: '/jobs?work_mode=REMOTE&offset=20' }),
      )
    })

    it('explains an empty page past the end rather than blaming the filters', async () => {
      const user = userEvent.setup()
      const list = mockList([], 50)
      renderPage('/jobs?offset=200')

      // Only reachable by editing the URL — Next disables itself at the end —
      // but "No jobs match those filters" would be a lie.
      await screen.findByText('That page is past the end of these results.')
      expect(screen.getByText('There are 50 jobs to show.')).toBeInTheDocument()

      await user.click(screen.getByRole('button', { name: 'Back to the first page' }))

      await waitFor(() => expect(currentUrl()).toBe('/jobs'))
      expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }))
    })
  })

  describe('the filters collapse on small screens', () => {
    /**
     * Below lg the four dropdowns hide behind a button, so three rows of
     * filters do not push the jobs off the first screen.
     *
     * The collapse itself is pure CSS. jsdom has no layout and this suite loads
     * no stylesheet, so nothing here can prove what a real viewport renders —
     * only that the classes and the wiring are present. The browser steps in
     * the plan cover the rest.
     */

    // /^Filters/ rather than an exact name: the accessible name becomes
    // "Filters 2 active" the moment a filter is set.
    const trigger = () => screen.getByRole('button', { name: /^Filters/ })
    // Resolved through aria-controls, so a dangling reference fails here too.
    const panel = () => document.getElementById(trigger().getAttribute('aria-controls') ?? '')!

    it('counts the active filters on the button', async () => {
      mockList([jobFixture()])
      renderPage('/jobs?work_mode=REMOTE&years_experience=0')
      await screen.findByRole('listitem')

      // years_experience=0 on purpose: the one value a truthiness check loses.
      expect(screen.getByRole('button', { name: 'Filters 2 active' })).toBeInTheDocument()
    })

    it('says nothing about filters the URL made up', async () => {
      mockList([jobFixture()])
      renderPage('/jobs?work_mode=BANANA&years_experience=99')
      await screen.findByRole('listitem')

      expect(trigger()).toHaveAccessibleName('Filters')
    })

    it('toggles the panel', async () => {
      const user = userEvent.setup()
      mockList([jobFixture()])
      renderPage()
      await screen.findByRole('listitem')

      expect(trigger()).toHaveAttribute('aria-expanded', 'false')
      expect(panel()).toHaveClass('hidden')

      await user.click(trigger())

      expect(trigger()).toHaveAttribute('aria-expanded', 'true')
      expect(panel()).toHaveClass('grid')
      expect(panel()).not.toHaveClass('hidden')
    })

    it('keeps the collapse to small screens', async () => {
      // A tripwire for a refactor that drops the breakpoint classes, and
      // nothing more: with no stylesheet in jsdom these strings have no effect
      // on rendering here at all.
      mockList([jobFixture()])
      renderPage()
      await screen.findByRole('listitem')

      expect(trigger().parentElement).toHaveClass('lg:hidden')
      expect(panel()).toHaveClass('lg:grid')
    })

    it('keeps the search box out of the collapse', async () => {
      // A product decision that is otherwise invisible: search is the control
      // people reach for first, so it stays on screen at every width.
      mockList([jobFixture()])
      renderPage()
      await screen.findByRole('listitem')

      expect(panel()).not.toContainElement(screen.getByLabelText('Search'))
      expect(panel()).toContainElement(screen.getByLabelText('Work mode'))
    })

    it('stays open while filters are chosen', async () => {
      // People set two and three filters at a time. Closing after each one
      // would make the panel hostile — and a filter write only replaces the
      // search params, so the component never remounts.
      const user = userEvent.setup()
      mockList([jobFixture()])
      renderPage()
      await screen.findByRole('listitem')
      await user.click(trigger())

      await user.selectOptions(screen.getByLabelText('Work mode'), 'REMOTE')

      await waitFor(() => expect(currentUrl()).toBe('/jobs?work_mode=REMOTE'))
      expect(trigger()).toHaveAttribute('aria-expanded', 'true')
    })

    it('closes on Escape and gives focus back to the button', async () => {
      const user = userEvent.setup()
      mockList([jobFixture()])
      renderPage()
      await screen.findByRole('listitem')
      await user.click(trigger())

      screen.getByLabelText('Work mode').focus()
      await user.keyboard('{Escape}')

      expect(trigger()).toHaveAttribute('aria-expanded', 'false')
      // Otherwise focus lands on <body> and tab order resets to the top of
      // the page.
      expect(trigger()).toHaveFocus()
    })

    it('lets Escape close the experience list before the panel', async () => {
      /*
       * The reason the Escape handler is a React handler on the card rather
       * than a document listener. comboboxCore stops propagation on Escape so
       * it does not reach an enclosing dialog; a document listener would fire
       * anyway and collapse the whole panel in the same keypress, losing the
       * user's place.
       */
      const user = userEvent.setup()
      mockList([jobFixture()])
      renderPage()
      await screen.findByRole('listitem')
      await user.click(trigger())

      await user.click(screen.getByLabelText('Your experience'))
      expect(screen.getByRole('listbox')).toBeInTheDocument()

      await user.keyboard('{Escape}')

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
      expect(trigger()).toHaveAttribute('aria-expanded', 'true')

      await user.keyboard('{Escape}')

      expect(trigger()).toHaveAttribute('aria-expanded', 'false')
    })
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
    //
    // The rule lives in setJobListFilter, at the write. It used to be an
    // effect watching the filters, which could not survive the move to the
    // URL: an effect also fires on mount, so arriving back at /jobs?offset=20
    // would have wiped the very offset the URL was restoring.
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
