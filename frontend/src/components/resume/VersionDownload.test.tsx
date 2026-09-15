import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { resumeService } from '@/services/resumeService'

import { VersionDownload } from './VersionDownload'

describe('VersionDownload', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('downloads the version it is sitting next to', async () => {
    /*
     * The point of the component. One Download button bound to whichever
     * version happened to be open meant retrieving an older file required
     * navigating to it first, and nothing on the page said so.
     */
    const user = userEvent.setup()
    const fetched = vi
      .spyOn(resumeService, 'downloadFile')
      .mockResolvedValue(new Blob(['%PDF-1.7']))

    render(<VersionDownload versionId="v1" filename="original.pdf" />)
    await user.click(screen.getByRole('button', { name: 'Download original.pdf' }))

    await waitFor(() => expect(fetched).toHaveBeenCalledWith('v1'))
  })

  it('names the file in its label, not just "Download"', async () => {
    // Several of these sit in one list. An unlabelled button is indistinguishable
    // from its neighbours to anyone using a screen reader.
    render(<VersionDownload versionId="v2" filename="tailored.pdf" />)

    expect(screen.getByRole('button', { name: 'Download tailored.pdf' })).toBeInTheDocument()
  })

  it('reports a failure next to the row that failed', async () => {
    // A banner at the top of a list of versions does not say which one broke.
    const user = userEvent.setup()
    vi.spyOn(resumeService, 'downloadFile').mockRejectedValue(new Error('offline'))

    render(<VersionDownload versionId="v1" filename="original.pdf" />)
    await user.click(screen.getByRole('button', { name: /Download/ }))

    expect(await screen.findByText(/Couldn't download/)).toBeInTheDocument()
  })
})
