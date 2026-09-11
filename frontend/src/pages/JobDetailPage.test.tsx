import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/services/apiClient'
import { applicationService } from '@/services/applicationService'
import { jobService } from '@/services/jobService'
import type { JobDetail, JobDetailLocationState } from '@/types/job'
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
    application: null,
    match_score: null,
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

function renderPage(state?: JobDetailLocationState) {
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
    // The page now mounts <SimilarJobs>, which fetches on its own. Stubbed to
    // DISABLED so these tests make no real request: the component swallows a
    // rejection silently, so an unmocked call would pass while attempting the
    // network — a latent flake rather than a failure.
    vi.spyOn(jobService, 'similar').mockResolvedValue({
      items: [],
      availability: 'DISABLED',
      limit: 6,
      model_name: null,
      model_version: null,
    })
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

  describe('going back to the list', () => {
    /**
     * The list keeps its filters in the URL, so this link has to carry them
     * back. A hard "/jobs" would drop them — which is the bug these tests
     * exist for, and the browser's own Back button is not the only way people
     * return.
     */

    const backLink = () => screen.getByRole('link', { name: '← Back to jobs' })

    it('names the page it returns to', async () => {
      /*
       * It read "Back to jobs" wherever it came from, so from Saved jobs it
       * both said and did the wrong thing. The label is read before the click —
       * that is the only thing it offers over the browser's own Back button
       * sitting a few pixels away — so it has to be true.
       */
      vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
      renderPage({ backTo: '/saved-jobs' })
      await screen.findByRole('heading', { name: 'Senior Data Engineer' })

      const link = screen.getByRole('link', { name: '← Back to saved jobs' })
      expect(link).toHaveAttribute('href', '/saved-jobs')
    })

    it('returns to the list you came from', async () => {
      vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
      renderPage({ backTo: '/jobs?q=python&offset=20' })
      await screen.findByRole('heading', { name: 'Senior Data Engineer' })

      expect(backLink()).toHaveAttribute('href', '/jobs?q=python&offset=20')
    })

    it('falls back to the plain list when the job was opened directly', async () => {
      // A pasted URL or a refresh: no state, and the link must still work.
      // Every in-app link now supplies it, so this is the arrived-from-nowhere
      // case rather than a gap in the callers.
      vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
      renderPage()
      await screen.findByRole('heading', { name: 'Senior Data Engineer' })

      expect(backLink()).toHaveAttribute('href', '/jobs')
    })

    it('refuses a back target that leaves the app', async () => {
      // History state is writable by any script on the page, and
      // <Link to="//evil.example"> renders a protocol-relative href that walks
      // off the origin.
      vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
      renderPage({ backTo: '//evil.example' })
      await screen.findByRole('heading', { name: 'Senior Data Engineer' })

      expect(backLink()).toHaveAttribute('href', '/jobs')
    })

    it('carries the duplicate notice and the back target together', async () => {
      // Two independent senders write this state. This is the test that fails
      // if someone replaces the object rather than adding a field to it.
      vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
      renderPage({ isDuplicate: true, backTo: '/jobs?offset=20' })
      await screen.findByRole('heading', { name: 'Senior Data Engineer' })

      expect(screen.getByText(/This posting was already here/)).toBeInTheDocument()
      expect(backLink()).toHaveAttribute('href', '/jobs?offset=20')
    })

    it('honours it on the error page too', async () => {
      // A second, separate link, above the split into JobDetailView — easy to
      // fix one and forget the other.
      vi.spyOn(jobService, 'get').mockRejectedValue(
        new ApiError(404, 'RESOURCE_NOT_FOUND', 'Nope.'),
      )
      renderPage({ backTo: '/jobs?q=python' })

      expect(await screen.findByRole('link', { name: 'Back to jobs' })).toHaveAttribute(
        'href',
        '/jobs?q=python',
      )
    })
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

  describe('saving and applying', () => {
    const boxes = () => screen.getAllByRole('checkbox', { name: 'I have applied' })

    /** Bookmark and funnel stage set separately — they are independent facts. */
    function application({
      saved = true,
      applied = false,
    }: { saved?: boolean; applied?: boolean } = {}) {
      return {
        id: 'a1',
        job_id: 'j1',
        status: applied ? ('APPLIED' as const) : ('SAVED' as const),
        is_saved: saved,
        applied_at: applied ? '2026-09-04T09:00:00Z' : null,
        created_at: '2026-09-04T08:00:00Z',
      }
    }

    it('offers the controls at the top and the bottom, in step', async () => {
      // Two copies, one hook. Two stateful components would each hold their own
      // pending flag and the header and footer would disagree mid-request.
      const user = userEvent.setup()
      vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
      vi.spyOn(applicationService, 'set').mockResolvedValue(application({ applied: true }))
      renderPage()

      await screen.findByRole('heading', { name: 'Senior Data Engineer' })
      expect(boxes()).toHaveLength(2)

      await user.click(boxes()[0]!)

      await waitFor(() => expect(boxes().every((box) => (box as HTMLInputElement).checked)).toBe(true))
    })

    it('shows the controls even when the job has no link to apply through', async () => {
      // "I have applied" is the user's own assertion, and a job with no link on
      // file is exactly one they may have applied to through the posting.
      vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture({ source_url: null }))
      renderPage()

      await screen.findByRole('heading', { name: 'Senior Data Engineer' })
      expect(boxes().length).toBeGreaterThan(0)
    })

    it('unticking keeps the job saved rather than removing it', async () => {
      const user = userEvent.setup()
      vi.spyOn(jobService, 'get').mockResolvedValue(
        detailFixture({ application: application({ applied: true }) }),
      )
      const set = vi.spyOn(applicationService, 'set').mockResolvedValue(application())
      const remove = vi.spyOn(applicationService, 'remove')
      renderPage()

      await screen.findByRole('heading', { name: 'Senior Data Engineer' })
      await user.click(boxes()[0]!)

      // The bookmark is carried through untouched; only `applied` changes.
      await waitFor(() =>
        expect(set).toHaveBeenCalledWith('j1', { saved: true, applied: false }),
      )
      expect(remove).not.toHaveBeenCalled()
    })

    it('reverts and explains when the server refuses', async () => {
      const user = userEvent.setup()
      vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
      vi.spyOn(applicationService, 'set').mockRejectedValue(
        new ApiError(500, 'INTERNAL_ERROR', 'Broke.'),
      )
      renderPage()

      await screen.findByRole('heading', { name: 'Senior Data Engineer' })
      await user.click(boxes()[0]!)

      expect(await screen.findByText('Broke.')).toBeInTheDocument()
      expect(boxes().every((box) => !(box as HTMLInputElement).checked)).toBe(true)
    })

    it('does not touch the bookmark when you mark a job applied', async () => {
      /*
       * The reported bug. Ticking "I have applied" used to send a single status
       * of APPLIED, which created the row and filled the bookmark — the
       * interface claiming the user had saved something they never saved.
       */
      const user = userEvent.setup()
      vi.spyOn(jobService, 'get').mockResolvedValue(detailFixture())
      const set = vi
        .spyOn(applicationService, 'set')
        .mockResolvedValue(application({ saved: false, applied: true }))
      renderPage()

      await screen.findByRole('heading', { name: 'Senior Data Engineer' })
      await user.click(boxes()[0]!)

      await waitFor(() =>
        expect(set).toHaveBeenCalledWith('j1', { saved: false, applied: true }),
      )
      // Still offering to save it, because it was never saved.
      expect(
        screen.getAllByRole('button', { name: /^Save Senior Data Engineer$/ }).length,
      ).toBeGreaterThan(0)
    })

    it('leaves a bookmarked job bookmarked when you mark it applied', async () => {
      const user = userEvent.setup()
      vi.spyOn(jobService, 'get').mockResolvedValue(
        detailFixture({ application: application() }),
      )
      const set = vi
        .spyOn(applicationService, 'set')
        .mockResolvedValue(application({ saved: true, applied: true }))
      renderPage()

      await screen.findByRole('heading', { name: 'Senior Data Engineer' })
      await user.click(boxes()[0]!)

      await waitFor(() => expect(set).toHaveBeenCalledWith('j1', { saved: true, applied: true }))
      expect(
        screen.getAllByRole('button', { name: /Remove Senior Data Engineer from saved/ }).length,
      ).toBeGreaterThan(0)
    })

    it('removes the bookmark without asking, and keeps that you applied', async () => {
      /*
       * There is no confirmation any more, and there should not be: un-bookmarking
       * an applied job no longer deletes anything. The dialog's warning — that the
       * job would leave Applications — became false when the two facts were split,
       * and a dialog stating something untrue is worse than none.
       */
      const user = userEvent.setup()
      vi.spyOn(jobService, 'get').mockResolvedValue(
        detailFixture({ application: application({ saved: true, applied: true }) }),
      )
      const set = vi
        .spyOn(applicationService, 'set')
        .mockResolvedValue(application({ saved: false, applied: true }))
      const remove = vi.spyOn(applicationService, 'remove')
      renderPage()

      await screen.findByRole('heading', { name: 'Senior Data Engineer' })
      await user.click(
        screen.getAllByRole('button', { name: /Remove Senior Data Engineer from saved/ })[0]!,
      )

      await waitFor(() => expect(set).toHaveBeenCalledWith('j1', { saved: false, applied: true }))
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(remove).not.toHaveBeenCalled()
      // Still applied, so the checkbox stays ticked.
      expect(boxes()[0]).toBeChecked()
    })

    it('drops the record when you untick applied on a job you never saved', async () => {
      // Neither bookmarked nor applied leaves nothing to remember, and the
      // server refuses a row that records nothing — so this is a DELETE.
      const user = userEvent.setup()
      vi.spyOn(jobService, 'get').mockResolvedValue(
        detailFixture({ application: application({ saved: false, applied: true }) }),
      )
      const set = vi.spyOn(applicationService, 'set')
      const remove = vi.spyOn(applicationService, 'remove').mockResolvedValue(undefined)
      renderPage()

      await screen.findByRole('heading', { name: 'Senior Data Engineer' })
      await user.click(boxes()[0]!)

      await waitFor(() => expect(remove).toHaveBeenCalledWith('j1'))
      expect(set).not.toHaveBeenCalled()
    })
  })
})
