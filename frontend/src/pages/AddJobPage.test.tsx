import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/services/apiClient'
import { jobService } from '@/services/jobService'
import type { JobDetail } from '@/types/job'
import { AddJobPage } from './AddJobPage'

const LONG_ENOUGH = 'Requirements\n- 5+ years of Python and PostgreSQL experience. '.repeat(6)

function detailFixture(overrides: Partial<JobDetail> = {}): JobDetail {
  return {
    id: 'j1',
    title: 'Senior Data Engineer',
    company: null,
    location: null,
    country_code: null,
    work_mode: null,
    employment_type: null,
    experience_level: null,
    min_years_experience: null,
    max_years_experience: null,
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    salary_period: null,
    posted_at: null,
    created_at: '2026-09-03T00:00:00Z',
    skill_count: 0,
    source: 'USER_SUBMITTED',
    source_url: null,
    status: 'ACTIVE',
    description_raw: LONG_ENOUGH,
    responsibilities: [],
    requirements: [],
    benefits: [],
    min_education: null,
    expires_at: null,
    skills: [],
    ...overrides,
  }
}

const APPLY_URL = 'https://example.com/careers/apply/1'

/**
 * `delay: null` removes user-event's inter-keystroke pause.
 *
 * Typing the URL and the overrides character by character is pure overhead —
 * nothing here asserts on timing, and at the default delay these tests were
 * exceeding the 5s timeout under a loaded full-suite run. The description is
 * pasted rather than typed for the same reason, and because pasting a posting
 * is what this page is actually for.
 */
const setup = () => userEvent.setup({ delay: null })

/** Renders the page plus a stand-in for the detail route it navigates to. */
function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/jobs/new']}>
      <Routes>
        <Route path="/jobs/new" element={<AddJobPage />} />
        <Route path="/jobs/:jobId" element={<div>detail page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('AddJobPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('will not submit an empty form', () => {
    renderPage()
    expect(screen.getByRole('button', { name: 'Add job' })).toBeDisabled()
  })

  it('says how much more is needed rather than failing after a round trip', async () => {
    // The server enforces the same minimum. Finding out after a request is
    // worse than being told while typing.
    const user = setup()
    const submit = vi.spyOn(jobService, 'submit')
    renderPage()

    await user.type(screen.getByLabelText(/Job description/), 'Backend Engineer')

    expect(screen.getByText(/of 200 characters/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add job' })).toBeDisabled()
    expect(submit).not.toHaveBeenCalled()
  })

  it('submits the description and navigates to the parsed job', async () => {
    const user = setup()
    const submit = vi
      .spyOn(jobService, 'submit')
      .mockResolvedValue({ job: detailFixture(), is_duplicate: false })
    renderPage()

    await user.click(screen.getByLabelText(/Job description/))
    await user.paste(LONG_ENOUGH)
    await user.type(screen.getByLabelText(/Link to apply/), APPLY_URL)
    await user.click(screen.getByRole('button', { name: 'Add job' }))

    await waitFor(() => expect(submit).toHaveBeenCalled())
    expect(submit.mock.calls[0]![0].description).toContain('Requirements')
    expect(await screen.findByText('detail page')).toBeInTheDocument()
  })

  it('sends the optional overrides only when filled in', async () => {
    // A blank override would otherwise overrule the parser with an empty
    // string and produce a job titled "".
    const user = setup()
    const submit = vi
      .spyOn(jobService, 'submit')
      .mockResolvedValue({ job: detailFixture(), is_duplicate: false })
    renderPage()

    await user.click(screen.getByLabelText(/Job description/))
    await user.paste(LONG_ENOUGH)
    await user.type(screen.getByLabelText('Company'), 'Zeta Labs')
    await user.type(screen.getByLabelText(/Link to apply/), APPLY_URL)
    await user.click(screen.getByRole('button', { name: 'Add job' }))

    await waitFor(() => expect(submit).toHaveBeenCalled())
    const sent = submit.mock.calls[0]![0]
    expect(sent.company).toBe('Zeta Labs')
    expect(sent.source_url).toBe(APPLY_URL)
    expect(sent).not.toHaveProperty('title')
  })

  it('surfaces a server refusal with its correlation id', async () => {
    const user = setup()
    vi.spyOn(jobService, 'submit').mockRejectedValue(
      new ApiError(422, 'VALIDATION_ERROR', 'That description is too short to parse.', {}, 'corr-9'),
    )
    renderPage()

    await user.click(screen.getByLabelText(/Job description/))
    await user.paste(LONG_ENOUGH)
    await user.type(screen.getByLabelText(/Link to apply/), APPLY_URL)
    await user.click(screen.getByRole('button', { name: 'Add job' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('too short to parse')
    expect(alert).toHaveTextContent('corr-9')
    // Still on the form, with the text intact, so nothing has to be re-pasted.
    expect(screen.getByLabelText(/Job description/)).toHaveValue(LONG_ENOUGH)
  })

  describe('the link to apply', () => {
    it('will not submit without one', async () => {
      // The link is the deliverable. Without it the job has no Apply button and
      // nobody can act on the posting.
      const user = setup()
      const submit = vi.spyOn(jobService, 'submit')
      renderPage()

      await user.click(screen.getByLabelText(/Job description/))
    await user.paste(LONG_ENOUGH)

      expect(screen.getByRole('button', { name: 'Add job' })).toBeDisabled()
      expect(submit).not.toHaveBeenCalled()
    })

    it('says so when it is not a link', async () => {
      const user = setup()
      renderPage()

      await user.click(screen.getByLabelText(/Job description/))
    await user.paste(LONG_ENOUGH)
      await user.type(screen.getByLabelText(/Link to apply/), 'not a url')

      expect(screen.getByText(/doesn't look like a link/)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Add job' })).toBeDisabled()
    })

    it('accepts one typed without https, as the server does', async () => {
      // The button's rule and the save's outcome have to agree, or the form
      // refuses something the API would have taken.
      const user = setup()
      renderPage()

      await user.click(screen.getByLabelText(/Job description/))
    await user.paste(LONG_ENOUGH)
      await user.type(screen.getByLabelText(/Link to apply/), 'careers.acme.com/jobs/1')

      expect(screen.getByRole('button', { name: 'Add job' })).toBeEnabled()
    })
  })
})
