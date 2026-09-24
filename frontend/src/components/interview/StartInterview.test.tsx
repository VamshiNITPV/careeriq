import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type * as ReactRouter from 'react-router-dom'
import { applicationService } from '@/services/applicationService'
import { interviewService } from '@/services/interviewService'
import { jobService } from '@/services/jobService'
import type { ApplicationListItem, ApplicationStatus } from '@/types/application'
import type { JobDetail } from '@/types/job'
import { MIN_DESCRIPTION_CHARS } from '@/types/job'

import { StartInterview } from './StartInterview'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof ReactRouter>('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})

/** Long enough that the client-side floor is not what the test is about. */
const POSTING = 'We need a backend engineer who knows Kafka and PostgreSQL. '.repeat(5)

/**
 * Pasted, not typed.
 *
 * `user.type` sends one event per character, and a job posting is 200 characters
 * minimum -- which took five seconds under full-suite contention and timed out.
 * It is also just wrong: nobody types a job advert into a box, they paste it.
 */
async function pasteInto(
  user: ReturnType<typeof userEvent.setup>,
  field: HTMLElement,
  text: string,
) {
  await user.click(field)
  await user.paste(text)
}

function application(
  overrides: { id?: string; status?: ApplicationStatus; title?: string; company?: string } = {},
): ApplicationListItem {
  const { id = 'a1', status = 'APPLIED', title = 'Backend Engineer', company = 'Acme' } = overrides
  return {
    id,
    job_id: `job-${id}`,
    status,
    is_saved: true,
    applied_at: '2026-09-12T10:00:00Z',
    created_at: '2026-09-12T10:00:00Z',
    job: {
      id: `job-${id}`,
      title,
      company: { id: 'c1', name: company, website: null, industry: null },
      location: 'Bengaluru',
      country_code: 'IN',
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
      created_at: '2026-09-01T10:00:00Z',
      skill_count: 6,
      application: null,
      match_score: null,
    },
  }
}

function added(id = 'j1', title = 'Backend Engineer') {
  return {
    job: { id, title } as JobDetail,
    is_duplicate: false,
  }
}

const renderForm = () =>
  render(
    <MemoryRouter>
      <StartInterview />
    </MemoryRouter>,
  )

async function choose(user: ReturnType<typeof userEvent.setup>, label: string) {
  // A real radio, so this is `getByRole` and a click. jsdom has no layout
  // engine, which rules out anything that depends on what is visible.
  await user.click(screen.getByRole('radio', { name: label }))
}

const started = { interview_id: 'new1', status: 'CREATED' as const, poll_url: '/x' }

describe('StartInterview', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    navigate.mockReset()
  })

  describe('the modes', () => {
    it('opens on the role field', () => {
      // Role is the default because it is the common case and the cheapest: no
      // list to fetch and nothing to paste.
      renderForm()

      expect(screen.getByRole('radio', { name: 'Just a role' })).toBeChecked()
      expect(
        screen.getByRole('textbox', { name: /role you are preparing for/i }),
      ).toBeInTheDocument()
    })

    it('swaps the fields rather than hiding them', async () => {
      // Rendered conditionally, never CSS-hidden: a hidden field is still in the
      // accessibility tree and still queryable, so this assertion would pass on
      // a bug if the panels were merely invisible.
      const user = userEvent.setup()
      renderForm()

      await choose(user, 'Paste a posting')

      expect(
        screen.queryByRole('textbox', { name: /role you are preparing for/i }),
      ).not.toBeInTheDocument()
      expect(screen.getByRole('textbox', { name: 'The posting' })).toBeInTheDocument()
    })
  })

  describe('pasting a posting', () => {
    it('adds the job first, then starts against it', async () => {
      const user = userEvent.setup()
      const submit = vi.spyOn(jobService, 'submit').mockResolvedValue(added('j1', 'AI Engineer'))
      const start = vi.spyOn(interviewService, 'start').mockResolvedValue(started)

      renderForm()
      await choose(user, 'Paste a posting')
      await pasteInto(user, screen.getByRole('textbox', { name: 'The posting' }), POSTING)
      await user.click(screen.getByRole('button', { name: 'Start' }))

      await waitFor(() => expect(start).toHaveBeenCalled())
      // The job's own id and its parsed title -- the id is what makes the topics
      // come from this posting rather than from the corpus average.
      expect(start).toHaveBeenCalledWith({
        target_role: 'AI Engineer',
        target_job_id: 'j1',
      })
      expect(submit.mock.calls[0]?.[0].description).toContain('Kafka')
      expect(navigate).toHaveBeenCalledWith('/interviews/new1')
    })

    it('sends no link when the box is empty', async () => {
      // The whole reason `source_url` became optional. A posting pasted from a
      // PDF or an email has no link, and ADR-019 forbids following one anyway.
      const user = userEvent.setup()
      const submit = vi.spyOn(jobService, 'submit').mockResolvedValue(added())
      vi.spyOn(interviewService, 'start').mockResolvedValue(started)

      renderForm()
      await choose(user, 'Paste a posting')
      await pasteInto(user, screen.getByRole('textbox', { name: 'The posting' }), POSTING)
      await user.click(screen.getByRole('button', { name: 'Start' }))

      await waitFor(() => expect(submit).toHaveBeenCalled())
      expect(submit.mock.calls[0]?.[0]).not.toHaveProperty('source_url')
    })

    it('refuses a malformed link rather than dropping it', async () => {
      // Absent and invalid are different answers. Silently discarding a typo
      // leaves the posting looking like one that never had a link.
      const user = userEvent.setup()
      const submit = vi.spyOn(jobService, 'submit')

      renderForm()
      await choose(user, 'Paste a posting')
      await pasteInto(user, screen.getByRole('textbox', { name: 'The posting' }), POSTING)
      await user.type(
        screen.getByRole('textbox', { name: /^link to the posting/i }),
        'javascript:alert(1)',
      )
      await user.click(screen.getByRole('button', { name: 'Start' }))

      expect(await screen.findByRole('alert')).toBeInTheDocument()
      expect(submit).not.toHaveBeenCalled()
    })

    it('refuses a posting the server would refuse anyway', async () => {
      // Checked against the shared constant rather than a literal, so the
      // button's state and the server's answer cannot drift.
      const user = userEvent.setup()
      const submit = vi.spyOn(jobService, 'submit')

      renderForm()
      await choose(user, 'Paste a posting')
      await pasteInto(
        user,
        screen.getByRole('textbox', { name: 'The posting' }),
        'x'.repeat(MIN_DESCRIPTION_CHARS - 1),
      )
      await user.click(screen.getByRole('button', { name: 'Start' }))

      expect(await screen.findByRole('alert')).toBeInTheDocument()
      expect(submit).not.toHaveBeenCalled()
    })

    it('does not start an interview when the posting could not be added', async () => {
      const user = userEvent.setup()
      vi.spyOn(jobService, 'submit').mockRejectedValue(new Error('not a posting'))
      const start = vi.spyOn(interviewService, 'start')

      renderForm()
      await choose(user, 'Paste a posting')
      await pasteInto(user, screen.getByRole('textbox', { name: 'The posting' }), POSTING)
      await user.click(screen.getByRole('button', { name: 'Start' }))

      expect(await screen.findByRole('alert')).toBeInTheDocument()
      expect(start).not.toHaveBeenCalled()
      expect(navigate).not.toHaveBeenCalled()
    })

    it('says where the posting went when only the interview failed', async () => {
      // The second half of a two-call flow. The job is a legitimate corpus row
      // either way, so the message points at it rather than implying the work
      // was lost.
      const user = userEvent.setup()
      vi.spyOn(jobService, 'submit').mockResolvedValue(added())
      vi.spyOn(interviewService, 'start').mockRejectedValue(new Error('no provider'))

      renderForm()
      await choose(user, 'Paste a posting')
      await pasteInto(user, screen.getByRole('textbox', { name: 'The posting' }), POSTING)
      await user.click(screen.getByRole('button', { name: 'Start' }))

      expect(await screen.findByRole('alert')).toHaveTextContent(/posting was saved/i)
    })

    it('prefers a typed role over the parsed title', async () => {
      // Job titles are noisy -- "Senior Backend Engineer (Payments) - Urgent" --
      // and `target_role` reaches the prompt verbatim.
      const user = userEvent.setup()
      vi.spyOn(jobService, 'submit').mockResolvedValue(added('j1', 'Urgent Hiring!! Backend'))
      const start = vi.spyOn(interviewService, 'start').mockResolvedValue(started)

      renderForm()
      await choose(user, 'Paste a posting')
      await pasteInto(user, screen.getByRole('textbox', { name: 'The posting' }), POSTING)
      await user.type(screen.getByRole('textbox', { name: 'Role (optional)' }), 'Backend Engineer')
      await user.click(screen.getByRole('button', { name: 'Start' }))

      await waitFor(() =>
        expect(start).toHaveBeenCalledWith({
          target_role: 'Backend Engineer',
          target_job_id: 'j1',
        }),
      )
    })
  })

  describe('picking a job you applied to', () => {
    it('does not fetch your applications until you ask for the picker', async () => {
      // Role is the default mode; making every visit pay for a list most people
      // will not open is a cost with no return.
      const list = vi.spyOn(applicationService, 'list')

      renderForm()

      expect(list).not.toHaveBeenCalled()
    })

    it('offers only jobs you actually applied to', async () => {
      const user = userEvent.setup()
      vi.spyOn(applicationService, 'list').mockResolvedValue({
        items: [
          application({ id: 'a1', status: 'APPLIED', title: 'Applied Role' }),
          application({ id: 'a2', status: 'INTERVIEW', title: 'Interviewing Role' }),
          application({ id: 'a3', status: 'SAVED', title: 'Saved Role' }),
          application({ id: 'a4', status: 'REJECTED', title: 'Rejected Role' }),
        ],
        total: 4,
      })

      renderForm()
      await choose(user, 'A job you applied to')
      await user.click(await screen.findByRole('combobox', { name: /which job/i }))

      expect(await screen.findByText('Applied Role')).toBeInTheDocument()
      expect(screen.getByText('Interviewing Role')).toBeInTheDocument()
      // A bookmark is a maybe, and a list of maybes buries the interviews you
      // actually have. Rejected is not reliably "a job you went for" at all.
      expect(screen.queryByText('Saved Role')).not.toBeInTheDocument()
      expect(screen.queryByText('Rejected Role')).not.toBeInTheDocument()
    })

    it('starts against the chosen job', async () => {
      const user = userEvent.setup()
      vi.spyOn(applicationService, 'list').mockResolvedValue({
        items: [application({ id: 'a1', title: 'Platform Engineer' })],
        total: 1,
      })
      const start = vi.spyOn(interviewService, 'start').mockResolvedValue(started)

      renderForm()
      await choose(user, 'A job you applied to')
      await user.click(await screen.findByRole('combobox', { name: /which job/i }))
      await user.click(await screen.findByText('Platform Engineer'))
      await user.click(screen.getByRole('button', { name: 'Start' }))

      await waitFor(() =>
        expect(start).toHaveBeenCalledWith({
          target_role: 'Platform Engineer',
          target_job_id: 'job-a1',
        }),
      )
    })

    it('finds a job by its company', async () => {
      // The company goes in `description`, which Combobox both shows and
      // searches -- so it is searchable at no extra cost.
      const user = userEvent.setup()
      vi.spyOn(applicationService, 'list').mockResolvedValue({
        items: [
          application({ id: 'a1', title: 'Backend Engineer', company: 'Zerodha' }),
          application({ id: 'a2', title: 'Platform Engineer', company: 'Razorpay' }),
        ],
        total: 2,
      })

      renderForm()
      await choose(user, 'A job you applied to')
      await user.type(await screen.findByRole('combobox', { name: /which job/i }), 'Razorpay')

      expect(await screen.findByText('Platform Engineer')).toBeInTheDocument()
      expect(screen.queryByText('Backend Engineer')).not.toBeInTheDocument()
    })

    it('says there is nothing to pick yet', async () => {
      const user = userEvent.setup()
      vi.spyOn(applicationService, 'list').mockResolvedValue({
        items: [application({ status: 'SAVED' })],
        total: 1,
      })

      renderForm()
      await choose(user, 'A job you applied to')

      // An empty dropdown reads as broken; this says what to do instead.
      expect(await screen.findByText(/nothing to pick yet/i)).toBeInTheDocument()
      expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    })

    it('keeps the other two ways working when the list fails', async () => {
      const user = userEvent.setup()
      vi.spyOn(applicationService, 'list').mockRejectedValue(new Error('down'))

      renderForm()
      await choose(user, 'A job you applied to')

      expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't load your applications/i)
      await choose(user, 'Just a role')
      expect(
        screen.getByRole('textbox', { name: /role you are preparing for/i }),
      ).toBeInTheDocument()
    })

    it('will not start without a job chosen', async () => {
      const user = userEvent.setup()
      vi.spyOn(applicationService, 'list').mockResolvedValue({
        items: [application()],
        total: 1,
      })
      const start = vi.spyOn(interviewService, 'start')

      renderForm()
      await choose(user, 'A job you applied to')
      await screen.findByRole('combobox', { name: /which job/i })
      await user.click(screen.getByRole('button', { name: 'Start' }))

      expect(await screen.findByRole('alert')).toBeInTheDocument()
      expect(start).not.toHaveBeenCalled()
    })
  })
})
