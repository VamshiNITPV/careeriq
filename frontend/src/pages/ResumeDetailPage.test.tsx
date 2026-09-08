import { render, screen, waitFor } from '@testing-library/react'
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

  it('keeps the page up when the career summary fails', async () => {
    vi.spyOn(resumeService, 'get').mockResolvedValue(detailFixture())
    vi.spyOn(resumeService, 'getVersion').mockResolvedValue(VERSION)
    vi.spyOn(careerService, 'summary').mockRejectedValue(new Error('boom'))

    renderPage()

    expect(await screen.findByTitle('Preview of resume.pdf')).toBeInTheDocument()
    expect(screen.getByText(/Couldn't load what this resume added/)).toBeInTheDocument()
  })
})
