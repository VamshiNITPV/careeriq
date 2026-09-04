import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/services/apiClient'
import { resumeService, skillService } from '@/services/resumeService'
import type {
  CandidateSkill,
  ProcessingStatusResponse,
  Resume,
  SuggestedSkill,
} from '@/types/resume'
import { ResumePage } from './ResumePage'

/**
 * Every test here pins a case where the page used to fail silently — the class
 * of bug where working code presents as broken.
 *
 * No MemoryRouter or AuthProvider: ResumePage consumes neither, and the service
 * modules are mocked directly, matching the convention in ProfilePage.test.tsx.
 */

const POLL = 1200
const MAX_ATTEMPTS = 50

function resumeFixture(overrides: Partial<Resume> = {}): Resume {
  return {
    id: 'r1',
    title: 'resume.pdf',
    is_primary: true,
    current_version_id: 'v1',
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    skill_count: 3,
    latest_version_id: 'v1',
    latest_version_status: 'COMPLETE',
    latest_version_error: null,
    ...overrides,
  }
}

function skillFixture(overrides: Partial<CandidateSkill> = {}): CandidateSkill {
  return {
    id: 's1',
    skill: { id: 'sk1', name: 'Python', category: 'Programming Languages' },
    proficiency: null,
    years_of_experience: null,
    extraction_confidence: '0.950',
    is_user_verified: false,
    last_used_year: null,
    created_at: '2026-09-01T00:00:00Z',
    ...overrides,
  }
}

function suggestionFixture(overrides: Partial<SuggestedSkill> = {}): SuggestedSkill {
  return {
    skill_id: 'sk9',
    name: 'REST APIs',
    confidence: '0.550',
    evidence: 'Built and documented service endpoints.',
    section: 'EXPERIENCE',
    ...overrides,
  }
}

function statusFixture(
  overrides: Partial<ProcessingStatusResponse> = {},
): ProcessingStatusResponse {
  return {
    version_id: 'v2',
    status: 'PARSING',
    percent: 65,
    stage_label: 'Finding sections and skills',
    error: null,
    is_terminal: false,
    ...overrides,
  }
}

/** Mocks the three calls the initial load makes. */
function mockLoad({
  resumes = [] as Resume[],
  skills = [] as CandidateSkill[],
  suggestions = [] as SuggestedSkill[],
} = {}) {
  vi.spyOn(resumeService, 'list').mockResolvedValue(resumes)
  vi.spyOn(skillService, 'mySkills').mockResolvedValue(skills)
  vi.spyOn(resumeService, 'suggestions').mockResolvedValue({
    version_id: 'v1',
    suggestions,
    unknown_terms: [],
  })
}

const pdf = () => new File(['%PDF-1.4 fake'], 'resume.pdf', { type: 'application/pdf' })

/**
 * The file input carries no label, so it cannot be queried by role or name.
 * Noted rather than worked around — labelling it is accessibility work, which
 * is out of scope for this pass.
 */
const fileInput = () => document.querySelector<HTMLInputElement>('input[type="file"]')!

describe('ResumePage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('loading', () => {
    it('reports a failed load instead of showing an empty account', async () => {
      // The worst of the lot: a network blip told the user their resumes were
      // gone, as a statement of fact.
      vi.spyOn(resumeService, 'list').mockRejectedValue(new Error('offline'))
      vi.spyOn(skillService, 'mySkills').mockResolvedValue([])
      render(<ResumePage />)

      expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't load your resumes/i)
      expect(screen.queryByText('Nothing uploaded yet.')).not.toBeInTheDocument()
    })

    it('reports a failure from the skills half of the load too', async () => {
      // Promise.all means either rejection blanks both sections.
      vi.spyOn(resumeService, 'list').mockResolvedValue([])
      vi.spyOn(skillService, 'mySkills').mockRejectedValue(new Error('offline'))
      render(<ResumePage />)

      expect(await screen.findByRole('alert')).toBeInTheDocument()
      expect(screen.queryByText('Nothing uploaded yet.')).not.toBeInTheDocument()
    })

    it('surfaces the correlation id when the server sends one', async () => {
      vi.spyOn(resumeService, 'list').mockRejectedValue(
        new ApiError(500, 'INTERNAL_ERROR', 'Something broke.', {}, 'corr-7'),
      )
      vi.spyOn(skillService, 'mySkills').mockResolvedValue([])
      render(<ResumePage />)

      expect(await screen.findByRole('alert')).toHaveTextContent('corr-7')
    })

    it('Try again refetches and recovers', async () => {
      const user = userEvent.setup()
      vi.spyOn(resumeService, 'list')
        .mockRejectedValueOnce(new Error('offline'))
        .mockResolvedValue([resumeFixture()])
      vi.spyOn(skillService, 'mySkills').mockResolvedValue([])
      vi.spyOn(resumeService, 'suggestions').mockResolvedValue({
        version_id: 'v1',
        suggestions: [],
        unknown_terms: [],
      })
      render(<ResumePage />)

      await user.click(await screen.findByRole('button', { name: 'Try again' }))

      expect(await screen.findByText('resume.pdf')).toBeInTheDocument()
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

    it('does not tell a user with skills to go upload a resume', async () => {
      // The skills empty state was ungated, so it rendered during every load.
      mockLoad({ resumes: [resumeFixture()], skills: [skillFixture()] })
      render(<ResumePage />)

      expect(screen.queryByText(/add skills by hand below/)).not.toBeInTheDocument()
      expect(await screen.findByText('Python')).toBeInTheDocument()
      expect(screen.queryByText(/add skills by hand below/)).not.toBeInTheDocument()
    })
  })

  it('shows when a resume was uploaded, with the time', async () => {
    // Structure, not an exact string: the suite pins no TZ, so the rendered
    // clock time depends on the machine. A named month and a time separator
    // are what was asked for, and they hold in every timezone.
    mockLoad({ resumes: [resumeFixture()] })
    render(<ResumePage />)

    const added = within(await screen.findByRole('listitem')).getByText(/^Added /)
    // Day before the month, month as a name, then a time. The day number can
    // shift with the machine's timezone, so it is not asserted.
    expect(added).toHaveTextContent(/Added \d{1,2} Sept? 2026, \d{1,2}:\d{2}/)
  })

  describe('upload', () => {
    it('explains a duplicate instead of appearing to do nothing', async () => {
      const user = userEvent.setup()
      mockLoad()
      vi.spyOn(resumeService, 'upload').mockResolvedValue({
        resume_id: 'r1',
        version_id: 'v1',
        status: 'COMPLETE',
        is_duplicate: true,
        poll_url: '/x',
      })
      const poll = vi.spyOn(resumeService, 'status')
      render(<ResumePage />)
      await screen.findByText('Nothing uploaded yet.')

      await user.upload(fileInput(), pdf())

      expect(await screen.findByText(/already uploaded that file/i)).toBeInTheDocument()
      // Nothing to poll — the server reused the earlier parse.
      expect(poll).not.toHaveBeenCalled()
    })

    it('reports an upload failure with its reason', async () => {
      const user = userEvent.setup()
      mockLoad()
      vi.spyOn(resumeService, 'upload').mockRejectedValue(
        new ApiError(413, 'PAYLOAD_TOO_LARGE', 'File exceeds 5 MB.', {}, 'corr-1'),
      )
      render(<ResumePage />)
      await screen.findByText('Nothing uploaded yet.')

      await user.upload(fileInput(), pdf())

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent('File exceeds 5 MB.')
      // Previously dropped, because upload built its ApiError without one.
      expect(alert).toHaveTextContent('corr-1')
    })
  })

  describe('processing', () => {
    it('explains a failure even when the server sends no message', async () => {
      const user = userEvent.setup()
      mockLoad()
      vi.spyOn(resumeService, 'upload').mockResolvedValue({
        resume_id: 'r1',
        version_id: 'v2',
        status: 'PENDING',
        is_duplicate: false,
        poll_url: '/x',
      })
      vi.spyOn(resumeService, 'status').mockResolvedValue(
        statusFixture({ status: 'FAILED', error: null, is_terminal: true, percent: 100 }),
      )
      render(<ResumePage />)
      await screen.findByText('Nothing uploaded yet.')

      await user.upload(fileInput(), pdf())

      // The condition used to require a non-null error, so this rendered
      // nothing at all.
      expect(await screen.findByText(/something went wrong reading this document/i)).toBeInTheDocument()
    })

    it('hides the progress bar when it gives up, and offers a way back', async () => {
      // fireEvent rather than user-event: user-event's internal waits do not
      // resolve under fake timers even with `advanceTimers` wired up, and the
      // test hangs with no useful message. fireEvent is synchronous and needs
      // no such bridge.
      vi.useFakeTimers()
      mockLoad()
      vi.spyOn(resumeService, 'upload').mockResolvedValue({
        resume_id: 'r1',
        version_id: 'v2',
        status: 'PENDING',
        is_duplicate: false,
        poll_url: '/x',
      })
      const poll = vi.spyOn(resumeService, 'status').mockResolvedValue(statusFixture())
      render(<ResumePage />)
      await act(async () => {})

      await act(async () => {
        fireEvent.change(fileInput(), { target: { files: [pdf()] } })
      })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL * MAX_ATTEMPTS)
      })

      expect(screen.getByText(/still working on it/i)).toBeInTheDocument()
      // The warning used to render on top of a bar that was still animating.
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()

      poll.mockClear()
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Check again' }))
      })

      expect(poll).toHaveBeenCalledWith('v2')
    })
  })

  describe('a resume whose parse failed', () => {
    const failed = resumeFixture({
      current_version_id: null,
      latest_version_id: 'v7',
      latest_version_status: 'FAILED',
      latest_version_error: 'No text could be read from this document.',
      skill_count: 0,
    })

    it('says so, and offers Try again against the failed version', async () => {
      // It used to look identical to a healthy resume, with no button at all:
      // the pipeline never sets current_version_id on failure, and that is what
      // the button was gated on. Delete and re-upload was the only recovery.
      const user = userEvent.setup()
      mockLoad({ resumes: [failed] })
      const reparse = vi.spyOn(resumeService, 'reparse').mockResolvedValue({
        resume_id: 'r1',
        version_id: 'v7',
        status: 'PENDING',
        is_duplicate: false,
        poll_url: '/x',
      })
      vi.spyOn(resumeService, 'status').mockResolvedValue(
        statusFixture({ is_terminal: true, status: 'COMPLETE' }),
      )
      render(<ResumePage />)

      const row = within(await screen.findByRole('listitem'))
      expect(row.getByText(/couldn't be read/i)).toBeInTheDocument()
      expect(row.getByText('No text could be read from this document.')).toBeInTheDocument()

      await user.click(row.getByRole('button', { name: 'Try again' }))

      expect(reparse).toHaveBeenCalledWith('v7')
    })

    it('shows a processing badge and blocks the row while the server works', async () => {
      mockLoad({
        resumes: [resumeFixture({ latest_version_status: 'PARSING', current_version_id: null })],
      })
      render(<ResumePage />)

      const row = within(await screen.findByRole('listitem'))
      expect(row.getByText(/processing/i)).toBeInTheDocument()
      expect(row.getByRole('button', { name: 'Re-extract' })).toBeDisabled()
    })
  })

  describe('failures that used to be silent', () => {
    it('reports a failed re-extract and keeps the row', async () => {
      const user = userEvent.setup()
      mockLoad({ resumes: [resumeFixture()] })
      vi.spyOn(resumeService, 'reparse').mockRejectedValue(new Error('offline'))
      render(<ResumePage />)

      await user.click(await screen.findByRole('button', { name: 'Re-extract' }))

      expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't start that again/i)
      expect(screen.getByText('resume.pdf')).toBeInTheDocument()
    })

    it('reports a failed skill removal and keeps the chip', async () => {
      const user = userEvent.setup()
      mockLoad({ resumes: [resumeFixture()], skills: [skillFixture()] })
      vi.spyOn(skillService, 'remove').mockRejectedValue(new Error('offline'))
      render(<ResumePage />)

      await user.click(await screen.findByRole('button', { name: 'Remove Python' }))

      expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't remove that skill/i)
      expect(screen.getByText('Python')).toBeInTheDocument()
    })

    it('reports a failed suggestion add and does not dismiss it', async () => {
      // The dismissal used to fire regardless, so a failed add looked like a
      // successful one until the page was reloaded.
      const user = userEvent.setup()
      mockLoad({ resumes: [resumeFixture()], suggestions: [suggestionFixture()] })
      vi.spyOn(skillService, 'add').mockRejectedValue(new Error('offline'))
      render(<ResumePage />)

      await user.click(await screen.findByRole('button', { name: 'Add' }))

      expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't add that skill/i)
      expect(screen.getByText('REST APIs')).toBeInTheDocument()
    })

    it('says so when suggestions could not be loaded', async () => {
      // An empty list is indistinguishable from "the parser found nothing".
      vi.spyOn(resumeService, 'list').mockResolvedValue([resumeFixture()])
      vi.spyOn(skillService, 'mySkills').mockResolvedValue([])
      vi.spyOn(resumeService, 'suggestions').mockRejectedValue(new Error('500'))
      render(<ResumePage />)

      expect(await screen.findByText(/couldn't load suggested skills/i)).toBeInTheDocument()
    })

    it('runs one request per double-click', async () => {
      const user = userEvent.setup()
      mockLoad({ resumes: [resumeFixture()] })
      let release = () => {}
      vi.spyOn(resumeService, 'reparse').mockReturnValue(
        new Promise((resolve) => {
          release = () =>
            resolve({
              resume_id: 'r1',
              version_id: 'v1',
              status: 'PENDING',
              is_duplicate: false,
              poll_url: '/x',
            })
        }),
      )
      vi.spyOn(resumeService, 'status').mockResolvedValue(
        statusFixture({ is_terminal: true, status: 'COMPLETE' }),
      )
      render(<ResumePage />)

      const button = await screen.findByRole('button', { name: 'Re-extract' })
      await user.click(button)
      await user.click(button)

      expect(button).toHaveAttribute('aria-busy', 'true')
      expect(resumeService.reparse).toHaveBeenCalledTimes(1)
      await act(async () => release())
    })
  })

  describe('delete', () => {
    it('shows a failure inside the dialog, where the user can see it', async () => {
      /**
       * ConfirmDialog uses showModal(), which makes the rest of the document
       * inert — so the page-level alert this used to set was rendered behind
       * the backdrop and was literally invisible, while the dialog sat there
       * with its spinner stopped.
       */
      const user = userEvent.setup()
      mockLoad({ resumes: [resumeFixture()] })
      vi.spyOn(resumeService, 'remove').mockRejectedValue(new Error('offline'))
      render(<ResumePage />)

      await user.click(await screen.findByRole('button', { name: 'Delete' }))
      await user.click(screen.getByRole('button', { name: 'Delete resume' }))

      const dialog = screen.getByRole('dialog')
      expect(await within(dialog).findByRole('alert')).toHaveTextContent(
        'Could not delete that resume.',
      )
    })

    it('names the consequence and removes the resume on confirm', async () => {
      const user = userEvent.setup()
      const listed = vi.spyOn(resumeService, 'list').mockResolvedValue([resumeFixture()])
      vi.spyOn(skillService, 'mySkills').mockResolvedValue([])
      vi.spyOn(resumeService, 'suggestions').mockResolvedValue({
        version_id: 'v1',
        suggestions: [],
        unknown_terms: [],
      })
      const remove = vi.spyOn(resumeService, 'remove').mockResolvedValue({ message: 'ok' })
      render(<ResumePage />)

      await user.click(await screen.findByRole('button', { name: 'Delete' }))
      const dialog = screen.getByRole('dialog')
      expect(within(dialog).getByText('3 skills')).toBeInTheDocument()

      listed.mockResolvedValue([])
      await user.click(within(dialog).getByRole('button', { name: 'Delete resume' }))

      await waitFor(() => expect(remove).toHaveBeenCalledWith('r1'))
      expect(await screen.findByText('Nothing uploaded yet.')).toBeInTheDocument()
    })
  })

  it('keeps only one banner at a time', async () => {
    // "Resume processed. Your skills are below." was conditioned only on the
    // last poll result, which nothing ever cleared — so it congratulated the
    // user over an empty skills section long after the fact.
    const user = userEvent.setup()
    mockLoad({ resumes: [resumeFixture()], skills: [skillFixture()] })
    vi.spyOn(resumeService, 'upload').mockResolvedValue({
      resume_id: 'r1',
      version_id: 'v2',
      status: 'PENDING',
      is_duplicate: false,
      poll_url: '/x',
    })
    vi.spyOn(resumeService, 'status').mockResolvedValue(
      statusFixture({ status: 'COMPLETE', is_terminal: true, percent: 100 }),
    )
    vi.spyOn(skillService, 'remove').mockResolvedValue({ message: 'ok' })
    render(<ResumePage />)
    await screen.findByText('Python')

    await user.upload(fileInput(), pdf())
    expect(await screen.findByText(/resume processed/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Remove Python' }))

    await waitFor(() => expect(screen.queryByText(/resume processed/i)).not.toBeInTheDocument())
  })
})
