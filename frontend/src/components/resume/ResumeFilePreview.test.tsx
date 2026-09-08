import { render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'
import { resumeService } from '@/services/resumeService'
import { ResumeFilePreview } from './ResumeFilePreview'

/**
 * The object-URL lifecycle, which is the only thing here that can leak.
 *
 * A 5MB blob per navigation, never revoked, is a crash on a phone rather than a
 * theoretical problem — so three of these tests exist purely to pin the
 * create/revoke pairing. jsdom does not implement `URL.createObjectURL`; the
 * shim lives in src/test/setup.ts and hands back a counter-suffixed string, so
 * a test can prove the *first* URL was the one revoked.
 */

const PDF = { versionId: 'v1', mimeType: 'application/pdf', filename: 'resume.pdf', fileSizeBytes: 1024 }
const DOCX = {
  versionId: 'v1',
  mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  filename: 'resume.docx',
  fileSizeBytes: 2048,
}

describe('ResumeFilePreview', () => {
  let create: MockInstance<(obj: Blob | MediaSource) => string>
  let revoke: MockInstance<(url: string) => void>

  beforeEach(() => {
    create = vi.spyOn(URL, 'createObjectURL')
    revoke = vi.spyOn(URL, 'revokeObjectURL')
    vi.spyOn(resumeService, 'downloadFile').mockResolvedValue(new Blob(['%PDF-1.7']))
  })

  it('renders the document once it has been fetched', async () => {
    render(<ResumeFilePreview {...PDF} />)

    const frame = await screen.findByTitle('Preview of resume.pdf')
    expect(frame).toHaveAttribute('src', create.mock.results[0]?.value)
  })

  it('revokes the object URL when it goes away', async () => {
    const { unmount } = render(<ResumeFilePreview {...PDF} />)
    await screen.findByTitle('Preview of resume.pdf')
    const url = create.mock.results[0]?.value

    unmount()

    expect(revoke).toHaveBeenCalledWith(url)
  })

  it('revokes the old URL when the version changes', async () => {
    const { rerender } = render(<ResumeFilePreview {...PDF} />)
    await screen.findByTitle('Preview of resume.pdf')
    const first = create.mock.results[0]?.value

    rerender(<ResumeFilePreview {...PDF} versionId="v2" />)
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2))

    expect(revoke).toHaveBeenCalledWith(first)
  })

  it('creates nothing when the fetch resolves after unmount', async () => {
    /*
     * The ordering test, and the one a naive implementation fails: the cancelled
     * flag has to be checked BEFORE createObjectURL. Creating the URL first and
     * bailing afterwards is the leak — cleanup has already run by then, closing
     * over a value that was still null, so nothing ever revokes it.
     */
    let resolve!: (blob: Blob) => void
    vi.spyOn(resumeService, 'downloadFile').mockReturnValue(
      new Promise<Blob>((r) => {
        resolve = r
      }),
    )
    const { unmount } = render(<ResumeFilePreview {...PDF} />)

    unmount()
    resolve(new Blob(['%PDF-1.7']))
    await Promise.resolve()

    expect(create).not.toHaveBeenCalled()
  })

  it('pairs every create with a revoke under StrictMode', async () => {
    // main.tsx renders under StrictMode, which double-invokes effects. This is
    // the one place the test default differs from production.
    const { unmount } = render(
      <StrictMode>
        <ResumeFilePreview {...PDF} />
      </StrictMode>,
    )
    await screen.findByTitle('Preview of resume.pdf')

    unmount()

    expect(revoke.mock.calls.length).toBe(create.mock.calls.length)
  })

  it('offers a download instead of a preview for a Word file', async () => {
    render(<ResumeFilePreview {...DOCX} />)

    expect(await screen.findByText(/can't be shown in the browser/i)).toBeInTheDocument()
    expect(screen.queryByTitle(/^Preview of/)).not.toBeInTheDocument()
    // Pulling megabytes down to render nothing is pure waste; the file is
    // fetched only if Download is pressed.
    expect(resumeService.downloadFile).not.toHaveBeenCalled()
  })

  it('recovers when the file cannot be fetched', async () => {
    vi.spyOn(resumeService, 'downloadFile').mockRejectedValue(new Error('offline'))
    render(<ResumeFilePreview {...PDF} />)

    expect(await screen.findByText(/couldn't show this file/i)).toBeInTheDocument()
    expect(screen.queryByTitle(/^Preview of/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
