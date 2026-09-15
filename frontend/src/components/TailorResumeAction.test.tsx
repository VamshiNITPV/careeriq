import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { optimizationService } from '@/services/optimizationService'
import { resumeService } from '@/services/resumeService'
import type { Resume } from '@/types/resume'

import { TailorResumeAction } from './TailorResumeAction'

const navigate = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => {
  // `importOriginal` rather than an inline `import()` type: the lint rule bans
  // those, and this keeps every other export of the module real so `Link` and
  // `MemoryRouter` still work.
  const actual = await importOriginal<Record<string, unknown>>()
  return { ...actual, useNavigate: () => navigate }
})

function resume(overrides: Partial<Resume> = {}): Resume {
  // Spelled out rather than cast. An `as Resume` here hid a missing field and,
  // worse, an earlier version silently dropped `overrides` — so the test for a
  // failed parse was quietly asserting against a healthy resume and passing for
  // the wrong reason.
  return {
    id: 'r1',
    title: 'CV',
    is_primary: true,
    current_version_id: 'v1',
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    skill_count: 12,
    latest_version_id: 'v1',
    latest_version_status: 'COMPLETE',
    latest_version_error: null,
    ...overrides,
  }
}

const renderAction = () =>
  render(
    <MemoryRouter>
      <TailorResumeAction jobId="j1" />
    </MemoryRouter>,
  )

describe('TailorResumeAction', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    navigate.mockClear()
  })

  it('starts an analysis against the resume that last parsed', async () => {
    /*
     * `current_version_id` rather than `latest_version_id`: a version whose
     * parse failed has no usable text, so tailoring it would spend a model call
     * to produce suggestions grounded in nothing.
     */
    const user = userEvent.setup()
    vi.spyOn(resumeService, 'list').mockResolvedValue([resume()])
    const analyze = vi.spyOn(optimizationService, 'analyze').mockResolvedValue({
      analysis_id: 'a1',
      status: 'PENDING',
      poll_url: '/api/v1/optimize/a1',
    })

    renderAction()
    await user.click(await screen.findByRole('button', { name: 'Suggest changes' }))

    await waitFor(() => expect(analyze).toHaveBeenCalledWith('v1', 'j1'))
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/optimize/a1'))
  })

  it('skips a resume whose parse never succeeded', async () => {
    // Offering to tailor it would fail later, after the reader had waited.
    vi.spyOn(resumeService, 'list').mockResolvedValue([
      resume({ current_version_id: null, latest_version_status: 'FAILED' }),
    ])

    renderAction()

    expect(await screen.findByRole('link', { name: 'Upload a resume' })).toBeInTheDocument()
  })

  it('asks for a resume when there is none', async () => {
    vi.spyOn(resumeService, 'list').mockResolvedValue([])

    renderAction()

    expect(await screen.findByRole('link', { name: 'Upload a resume' })).toHaveAttribute(
      'href',
      '/resume',
    )
  })

  it('says what the feature does before the reader commits to waiting', async () => {
    /*
     * Someone expecting "write me a better resume" should find out what this
     * actually does before a model call, not after one.
     */
    vi.spyOn(resumeService, 'list').mockResolvedValue([resume()])

    renderAction()

    expect(await screen.findByText(/Nothing is added/)).toBeInTheDocument()
  })

  it('stays on the page when starting fails', async () => {
    const user = userEvent.setup()
    vi.spyOn(resumeService, 'list').mockResolvedValue([resume()])
    vi.spyOn(optimizationService, 'analyze').mockRejectedValue(new Error('offline'))

    renderAction()
    await user.click(await screen.findByRole('button', { name: 'Suggest changes' }))

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(navigate).not.toHaveBeenCalled()
  })
})
