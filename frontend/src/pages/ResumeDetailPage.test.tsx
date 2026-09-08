import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/services/apiClient'
import { careerService } from '@/services/careerService'
import { resumeService } from '@/services/resumeService'
import { ErrorCode } from '@/types/api'
import type { ResumeDetail, ResumeVersionDetail } from '@/types/resume'
import { ResumeDetailPage } from './ResumeDetailPage'

const VERSION: ResumeVersionDetail = {
  id: 'v7',
  version_number: 1,
  original_filename: 'resume.pdf',
  mime_type: 'application/pdf',
  file_size_bytes: 1024,
  processing_status: 'COMPLETE',
  processing_error: null,
  processed_at: '2026-09-04T09:00:00Z',
  created_at: '2026-09-04T08:59:00Z',
  raw_text: 'PRIYA SHARMA\nBackend engineer',
  parsed_sections: {
    page_count: 2,
    character_count: 4821,
    sections: [
      { type: 'EXPERIENCE', heading: 'WORK EXPERIENCE', start: 0, end: 10, length: 10 },
      { type: 'EDUCATION', heading: null, start: 10, end: 20, length: 10 },
    ],
  },
  parsed_entities: {
    skills: [
      { name: 'FastAPI', confidence: 0.62, mentions: 1, section: 'SKILLS', matched: [], span: [], accepted: false },
      { name: 'Python', confidence: 0.95, mentions: 4, section: 'SKILLS', matched: [], span: [], accepted: true },
    ],
  },
}

function detailFixture(overrides: Partial<ResumeDetail> = {}): ResumeDetail {
  return {
    id: 'r1',
    title: 'resume.pdf',
    is_primary: true,
    current_version_id: 'v7',
    created_at: '2026-09-04T08:59:00Z',
    updated_at: '2026-09-04T09:00:00Z',
    skill_count: 2,
    latest_version_id: 'v7',
    latest_version_status: 'COMPLETE',
    latest_version_error: null,
    versions: [
      {
        id: 'v7',
        version_number: 1,
        original_filename: 'resume.pdf',
        mime_type: 'application/pdf',
        file_size_bytes: 1024,
        processing_status: 'COMPLETE',
        processing_error: null,
        processed_at: '2026-09-04T09:00:00Z',
        created_at: '2026-09-04T08:59:00Z',
      },
    ],
    ...overrides,
  }
}

const EMPTY_CAREER = { experiences: [], education: [], projects: [], certifications: [] }

function renderPage(entry = '/resume/r1') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/resume/:resumeId" element={<ResumeDetailPage />} />
        <Route path="/resume" element={<h1>Resumes</h1>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ResumeDetailPage', () => {
  beforeEach(() => {
    vi.spyOn(careerService, 'summary').mockResolvedValue(EMPTY_CAREER)
    vi.spyOn(resumeService, 'downloadFile').mockResolvedValue(new Blob(['%PDF-1.7']))
  })

  it('shows the document and what was read from it', async () => {
    vi.spyOn(resumeService, 'get').mockResolvedValue(detailFixture())
    vi.spyOn(resumeService, 'getVersion').mockResolvedValue(VERSION)

    renderPage()

    expect(await screen.findByTitle('Preview of resume.pdf')).toBeInTheDocument()
    expect(screen.getByText(/2 pages, 4,821 characters/)).toBeInTheDocument()
    expect(screen.getByText('WORK EXPERIENCE')).toBeInTheDocument()
    // A section with no heading falls back to its type rather than rendering blank.
    expect(screen.getByText('EDUCATION')).toBeInTheDocument()
  })

  it('sorts skills by confidence and marks the ones needing review', async () => {
    vi.spyOn(resumeService, 'get').mockResolvedValue(detailFixture())
    vi.spyOn(resumeService, 'getVersion').mockResolvedValue(VERSION)

    renderPage()

    // 95%, not NaN%: parsed_entities confidences are raw numbers, unlike the
    // suggestion endpoint's, which are Decimal-serialised strings.
    expect(await screen.findByText('Python · 95%')).toBeInTheDocument()
    expect(screen.getByText(/FastAPI · 62% · needs review/)).toBeInTheDocument()
  })

  it('opens the version that exists, not the one that parsed cleanly', async () => {
    /*
     * The load-bearing choice. `current_version_id` is null for a resume whose
     * every parse failed, so selecting it would leave the page blank for
     * precisely the resume someone most wants to inspect.
     */
    const getVersion = vi.spyOn(resumeService, 'getVersion').mockResolvedValue({
      ...VERSION,
      processing_status: 'FAILED',
      processing_error: 'No text could be extracted.',
    })
    vi.spyOn(resumeService, 'get').mockResolvedValue(
      detailFixture({ current_version_id: null, latest_version_status: 'FAILED' }),
    )

    renderPage()

    await waitFor(() => expect(getVersion).toHaveBeenCalledWith('v7'))
    expect(await screen.findByText('No text could be extracted.')).toBeInTheDocument()
    // The file still previews — extraction failed, not the upload.
    expect(screen.getByTitle('Preview of resume.pdf')).toBeInTheDocument()
  })

  it('survives a version parsed before those fields existed', async () => {
    // The JSONB was written by whatever pipeline was deployed at the time, so
    // an older row can simply lack keys. It must render, not crash.
    vi.spyOn(resumeService, 'get').mockResolvedValue(detailFixture())
    vi.spyOn(resumeService, 'getVersion').mockResolvedValue({
      ...VERSION,
      raw_text: null,
      parsed_sections: null,
      parsed_entities: null,
    })

    renderPage()

    expect(await screen.findByText(/No headings were found/)).toBeInTheDocument()
    expect(screen.getByText(/No skills were found/)).toBeInTheDocument()
    expect(screen.getByText(/No text could be read/)).toBeInTheDocument()
  })

  it('keeps the extracted text collapsed', async () => {
    vi.spyOn(resumeService, 'get').mockResolvedValue(detailFixture())
    vi.spyOn(resumeService, 'getVersion').mockResolvedValue(VERSION)

    renderPage()
    await screen.findByTitle('Preview of resume.pdf')

    // A 30,000-character resume would otherwise own the page.
    const disclosure = screen.getByText('Show the text we read').closest('details')
    expect(disclosure).not.toHaveAttribute('open')
  })

  it('says so when the resume is gone', async () => {
    vi.spyOn(resumeService, 'get').mockRejectedValue(
      new ApiError(404, ErrorCode.ResourceNotFound, 'Nope.'),
    )

    renderPage()

    expect(await screen.findByText('That resume no longer exists.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to resumes' })).toBeInTheDocument()
  })

  it('renders a resume that has no file at all', async () => {
    vi.spyOn(resumeService, 'get').mockResolvedValue(
      detailFixture({ current_version_id: null, latest_version_id: null, versions: [] }),
    )
    const getVersion = vi.spyOn(resumeService, 'getVersion')

    renderPage()

    expect(await screen.findByText('This resume has no uploaded file.')).toBeInTheDocument()
    expect(getVersion).not.toHaveBeenCalled()
  })

  it('ignores a version id this resume does not have', async () => {
    // A stale or hand-typed ?v= would otherwise 404 the second request on a
    // page that had otherwise loaded fine — a confusing half-broken state.
    vi.spyOn(resumeService, 'get').mockResolvedValue(detailFixture())
    const getVersion = vi.spyOn(resumeService, 'getVersion').mockResolvedValue(VERSION)

    renderPage('/resume/r1?v=not-a-real-version')

    await waitFor(() => expect(getVersion).toHaveBeenCalledWith('v7'))
  })

  describe('renaming and choosing the primary', () => {
    const openRename = async (user: ReturnType<typeof userEvent.setup>) =>
      user.click(await screen.findByRole('button', { name: 'Rename' }))

    it('renames without reloading the page', async () => {
      const user = userEvent.setup()
      const get = vi.spyOn(resumeService, 'get').mockResolvedValue(detailFixture())
      vi.spyOn(resumeService, 'getVersion').mockResolvedValue(VERSION)
      const rename = vi
        .spyOn(resumeService, 'rename')
        .mockResolvedValue({ ...detailFixture(), title: 'Backend CV' })

      renderPage()
      await openRename(user)

      const field = screen.getByLabelText('Resume name')
      // Prefilled and selected: the existing name is a raw filename people
      // almost always want to replace rather than append to.
      expect(field).toHaveValue('resume.pdf')
      await user.clear(field)
      await user.type(field, 'Backend CV{Enter}')

      await waitFor(() => expect(rename).toHaveBeenCalledWith('r1', 'Backend CV'))
      expect(await screen.findByRole('heading', { name: 'Backend CV' })).toBeInTheDocument()
      // The call-count assertion is the point. Without it, someone "simplifies"
      // the merge into load() and nothing fails — the only symptom is a
      // full-page spinner and a re-downloaded PDF on every rename.
      expect(get).toHaveBeenCalledTimes(1)
    })

    it('trims the name and refuses a blank one', async () => {
      const user = userEvent.setup()
      vi.spyOn(resumeService, 'get').mockResolvedValue(detailFixture())
      vi.spyOn(resumeService, 'getVersion').mockResolvedValue(VERSION)
      const rename = vi
        .spyOn(resumeService, 'rename')
        .mockResolvedValue({ ...detailFixture(), title: 'Backend CV' })

      renderPage()
      await openRename(user)
      const field = screen.getByLabelText('Resume name')

      await user.clear(field)
      await user.type(field, '   ')
      expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
      expect(rename).not.toHaveBeenCalled()

      await user.clear(field)
      await user.type(field, '  Backend CV  {Enter}')

      await waitFor(() => expect(rename).toHaveBeenCalledWith('r1', 'Backend CV'))
    })

    it('abandons the rename on Escape and gives focus back', async () => {
      const user = userEvent.setup()
      vi.spyOn(resumeService, 'get').mockResolvedValue(detailFixture())
      vi.spyOn(resumeService, 'getVersion').mockResolvedValue(VERSION)
      const rename = vi.spyOn(resumeService, 'rename')

      renderPage()
      await openRename(user)
      await user.type(screen.getByLabelText('Resume name'), 'nonsense')
      await user.keyboard('{Escape}')

      // level 1 to disambiguate: the file preview's own heading is the version's
      // filename, which happens to be the same string.
      expect(
        await screen.findByRole('heading', { level: 1, name: 'resume.pdf' }),
      ).toBeInTheDocument()
      expect(rename).not.toHaveBeenCalled()
      // Without the focus-return effect — which looks unnecessary — a keyboard
      // user who cancels lands on <body> with tab order reset to the top.
      expect(screen.getByRole('button', { name: 'Rename' })).toHaveFocus()
    })

    it('keeps the editor open with what was typed when the save fails', async () => {
      const user = userEvent.setup()
      vi.spyOn(resumeService, 'get').mockResolvedValue(detailFixture())
      vi.spyOn(resumeService, 'getVersion').mockResolvedValue(VERSION)
      vi.spyOn(resumeService, 'rename').mockRejectedValue(
        new ApiError(500, ErrorCode.InternalError, 'Nope.'),
      )

      renderPage()
      await openRename(user)
      const field = screen.getByLabelText('Resume name')
      await user.clear(field)
      await user.type(field, 'Backend CV{Enter}')

      expect(await screen.findByText('Nope.')).toBeInTheDocument()
      // Closing on failure would throw away what the user typed.
      expect(screen.getByLabelText('Resume name')).toHaveValue('Backend CV')
      expect(screen.queryByRole('heading', { name: 'Backend CV' })).not.toBeInTheDocument()
    })

    it('swaps the button for the badge once this resume is primary', async () => {
      const user = userEvent.setup()
      const get = vi
        .spyOn(resumeService, 'get')
        .mockResolvedValue(detailFixture({ is_primary: false }))
      vi.spyOn(resumeService, 'getVersion').mockResolvedValue(VERSION)
      const setPrimary = vi
        .spyOn(resumeService, 'setPrimary')
        .mockResolvedValue({ ...detailFixture(), is_primary: true })

      renderPage()
      await user.click(await screen.findByRole('button', { name: 'Make primary' }))

      await waitFor(() => expect(setPrimary).toHaveBeenCalledWith('r1'))
      // The swap is the feedback. Leaving the button up would invite a second
      // pointless PATCH.
      expect(screen.queryByRole('button', { name: 'Make primary' })).not.toBeInTheDocument()
      expect(screen.getByText('Primary')).toBeInTheDocument()
      expect(get).toHaveBeenCalledTimes(1)
    })

    it('offers no Make primary when this resume already is primary', async () => {
      vi.spyOn(resumeService, 'get').mockResolvedValue(detailFixture())
      vi.spyOn(resumeService, 'getVersion').mockResolvedValue(VERSION)

      renderPage()
      await screen.findByTitle('Preview of resume.pdf')

      // Hidden rather than disabled: nothing on this page could ever enable it.
      expect(screen.queryByRole('button', { name: 'Make primary' })).not.toBeInTheDocument()
      expect(screen.getByText('Primary')).toBeInTheDocument()
    })

    it('lets only one action be in flight', async () => {
      const user = userEvent.setup()
      vi.spyOn(resumeService, 'get').mockResolvedValue(detailFixture({ is_primary: false }))
      vi.spyOn(resumeService, 'getVersion').mockResolvedValue(VERSION)
      // Never resolves, so the request stays in flight for the assertion.
      vi.spyOn(resumeService, 'setPrimary').mockReturnValue(new Promise(() => {}))

      renderPage()
      await user.click(await screen.findByRole('button', { name: 'Make primary' }))

      // Both PATCH the same resource and both return a full resume, so
      // overlapping them lets a stale response overwrite a fresh one.
      expect(screen.getByRole('button', { name: 'Rename' })).toBeDisabled()
    })
  })

  it('keeps the page up when the career summary fails', async () => {
    vi.spyOn(resumeService, 'get').mockResolvedValue(detailFixture())
    vi.spyOn(resumeService, 'getVersion').mockResolvedValue(VERSION)
    vi.spyOn(careerService, 'summary').mockRejectedValue(new Error('boom'))

    renderPage()

    expect(await screen.findByTitle('Preview of resume.pdf')).toBeInTheDocument()
    expect(screen.getByText(/Couldn't load what this resume added/)).toBeInTheDocument()
  })
})
