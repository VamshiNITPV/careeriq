import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/services/apiClient'
import { jobService } from '@/services/jobService'
import type { JobDetail } from '@/types/job'
import { JobDetailPage } from './JobDetailPage'

function detailFixture(overrides: Partial<JobDetail> = {}): JobDetail {
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
    skill_count: 3,
    source: 'USER_SUBMITTED',
    source_url: 'https://example.com/jobs/1',
    status: 'ACTIVE',
    description_raw: 'The original pasted posting.',
    responsibilities: ['Build data pipelines'],
    requirements: ['4-7 years of experience'],
    benefits: ['Health insurance'],
    min_education: 'BACHELORS',
    expires_at: null,
    skills: [
      {
        skill_id: 's1',
        name: 'Python',
        requirement: 'REQUIRED',
        min_years: '4.0',
        extraction_confidence: '0.950',
      },
      {
        skill_id: 's2',
        name: 'PostgreSQL',
        requirement: 'REQUIRED',
        min_years: null,
        extraction_confidence: '0.950',
      },
      {
        skill_id: 's3',
        name: 'Kubernetes',
        requirement: 'PREFERRED',
        min_years: null,
        extraction_confidence: '0.900',
      },
    ],
    ...overrides,
  }
}

function renderPage(state?: { isDuplicate: boolean }) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/jobs/j1', state: state ?? null }]}>
      <Routes>
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />
        <Route path="/jobs" element={<div>jobs list</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('JobDetailPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('shows the parsed facts', async () => {
    vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Senior Data Engineer' })).toBeInTheDocument()
    expect(screen.getByText(/Zeta Payments/)).toBeInTheDocument()
    expect(screen.getByText('INR 2.8M – 4.5M/yr')).toBeInTheDocument()
    expect(screen.getByText('4–7 years')).toBeInTheDocument()
    expect(screen.getByText("Bachelor's degree")).toBeInTheDocument()
  })

  it('omits a fact the posting did not state', async () => {
    // A blank "Pay: —" row invites the reader to think the data was lost.
    vi.spyOn(jobService, 'get').mockResolvedValue(
      detailFixture({ salary_min: null, salary_max: null, min_education: null }),
    )
    renderPage()

    await screen.findByRole('heading', { name: 'Senior Data Engineer' })
    expect(screen.queryByText('Pay')).not.toBeInTheDocument()
    expect(screen.queryByText('Education')).not.toBeInTheDocument()
  })

  it('separates required skills from preferred ones', async () => {
    // The distinction the ranking formula weights, so it has to be visible.
    vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
    renderPage()

    const required = (await screen.findByRole('heading', { name: 'Required' })).parentElement!
    expect(within(required).getByText(/Python/)).toBeInTheDocument()
    expect(within(required).getByText('PostgreSQL')).toBeInTheDocument()

    const preferred = screen.getByRole('heading', { name: 'Preferred' }).parentElement!
    expect(within(preferred).getByText('Kubernetes')).toBeInTheDocument()
  })

  it('shows a per-skill minimum when the posting gave one', async () => {
    vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
    renderPage()

    expect(await screen.findByText('Python · 4+ yrs')).toBeInTheDocument()
  })

  it('keeps the original posting available when there is no link', async () => {
    // The fallback, and the reason it is one: the application link is usually
    // somewhere inside the text.
    vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture({ source_url: null }))
    renderPage()

    await screen.findByRole('heading', { name: 'Senior Data Engineer' })
    expect(screen.getByText('The original pasted posting.')).toBeInTheDocument()
  })

  it('hides the raw description when there is a link to apply through', async () => {
    vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
    renderPage()

    await screen.findByRole('heading', { name: 'Senior Data Engineer' })
    expect(screen.queryByText('The original pasted posting.')).not.toBeInTheDocument()
    expect(screen.queryByText(/Show the original description/)).not.toBeInTheDocument()
  })

  it('explains a duplicate submission', async () => {
    vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
    renderPage({ isDuplicate: true })

    expect(await screen.findByText(/already here/i)).toBeInTheDocument()
  })

  it('says nothing about duplicates on an ordinary visit', async () => {
    vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
    renderPage()

    await screen.findByRole('heading', { name: 'Senior Data Engineer' })
    expect(screen.queryByText(/already here/i)).not.toBeInTheDocument()
  })

  it('distinguishes a missing job from a failed request', async () => {
    vi.spyOn(jobService, 'get').mockRejectedValue(new ApiError(404, 'RESOURCE_NOT_FOUND', 'Nope.'))
    renderPage()

    expect(await screen.findByText('That job no longer exists.')).toBeInTheDocument()
  })

  it('offers a retry after a server error', async () => {
    const user = userEvent.setup()
    const get = vi
      .spyOn(jobService, 'get')
      .mockRejectedValueOnce(new ApiError(500, 'INTERNAL_ERROR', 'Broke.'))
      .mockResolvedValue(detailFixture())
    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Try again' }))

    expect(await screen.findByRole('heading', { name: 'Senior Data Engineer' })).toBeInTheDocument()
    expect(get).toHaveBeenCalledTimes(2)
  })

  describe('applying', () => {
    const applyLinks = () => screen.getAllByRole('link', { name: /Apply for this job/ })

    it('offers the same link at the top and at the bottom', async () => {
      // Without noreferrer the opened page can read where it was linked from,
      // and both copies need it — not just whichever one was written first.
      vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
      renderPage()

      await screen.findByRole('heading', { name: 'Senior Data Engineer' })
      const links = applyLinks()
      expect(links).toHaveLength(2)
      for (const link of links) {
        expect(link).toHaveAttribute('href', 'https://example.com/jobs/1')
        expect(link).toHaveAttribute('rel', 'noopener noreferrer')
        expect(link).toHaveAttribute('target', '_blank')
      }
      // Where it goes, before the click.
      expect(screen.getByText(/Opens example.com\/jobs\/1/)).toBeInTheDocument()
    })

    it('does not turn a stored javascript: link into an apply button', async () => {
      // These rows predate any validation, and the corpus is shared, so one
      // user's stored value renders on everyone's screen. Refusing it here is
      // the last line — and refusing means falling back, not failing.
      vi.spyOn(jobService, 'get').mockResolvedValue(
        detailFixture({ source_url: 'javascript:alert(1)' }),
      )
      renderPage()

      await screen.findByRole('heading', { name: 'Senior Data Engineer' })
      expect(screen.queryByRole('link', { name: /Apply for this job/ })).not.toBeInTheDocument()
      expect(screen.getByText('The original pasted posting.')).toBeInTheDocument()
    })

    it('says plainly when no link was given', async () => {
      // Never invents one — not a careers-page guess, not a search.
      vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture({ source_url: null }))
      renderPage()

      expect(await screen.findByText(/No application link was given/)).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: 'Add the application link' }),
      ).toBeInTheDocument()
    })

    it('adds a missing link and switches to the apply view', async () => {
      const user = userEvent.setup()
      vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture({ source_url: null }))
      const save = vi
        .spyOn(jobService, 'setApplicationLink')
        .mockResolvedValue(detailFixture({ source_url: 'https://acme.example/apply/9' }))
      renderPage()

      await user.click(await screen.findByRole('button', { name: 'Add the application link' }))
      await user.type(screen.getByLabelText('Application link'), 'acme.example/apply/9')
      await user.click(screen.getByRole('button', { name: 'Save' }))

      await waitFor(() => expect(save).toHaveBeenCalledWith('j1', 'acme.example/apply/9'))
      // No refetch — the page re-renders from the response.
      expect(applyLinks()).toHaveLength(2)
      expect(screen.queryByText('The original pasted posting.')).not.toBeInTheDocument()
    })

    it('recovers when someone else added a link first', async () => {
      // The corpus is shared, so this is a real race. A raw "conflict" would
      // be useless; reloading lands the user where they wanted to be anyway.
      const user = userEvent.setup()
      const get = vi
        .spyOn(jobService, 'get')
        .mockResolvedValueOnce(detailFixture({ source_url: null }))
        .mockResolvedValue(detailFixture({ source_url: 'https://someone.example/apply' }))
      vi.spyOn(jobService, 'setApplicationLink').mockRejectedValue(
        new ApiError(409, 'CONFLICT', 'This job already has an application link.'),
      )
      renderPage()

      await user.click(await screen.findByRole('button', { name: 'Add the application link' }))
      await user.type(screen.getByLabelText('Application link'), 'https://mine.example/apply')
      await user.click(screen.getByRole('button', { name: 'Save' }))

      await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
      expect(applyLinks()[0]).toHaveAttribute('href', 'https://someone.example/apply')
    })
  })
})
