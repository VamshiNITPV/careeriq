import { useState } from 'react'
import { saveBlob } from '@/hooks/useResumeFile'
import { resumeService } from '@/services/resumeService'

/**
 * Download one stored version, from wherever it is listed.
 *
 * Its own component because the list needs a download per row, and the existing
 * one in `ResumeFilePreview` is bound to whichever version is currently open.
 * Without this, retrieving an older file meant navigating to it first — and
 * nothing on the page said so, which is why "how do I get my old version back"
 * was a reasonable question to have to ask.
 *
 * A button rather than a link: the endpoint needs an Authorization header, and
 * a browser navigation sends none, so an `<a href>` would simply 401.
 */
export function VersionDownload({
  versionId,
  filename,
}: {
  versionId: string
  filename: string
}) {
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  async function download() {
    setFailed(false)
    setBusy(true)
    try {
      saveBlob(await resumeService.downloadFile(versionId), filename)
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        disabled={busy}
        onClick={() => void download()}
        aria-label={`Download ${filename}`}
        className="text-xs font-medium text-indigo-600 underline disabled:text-slate-400"
      >
        {busy ? 'Downloading…' : 'Download'}
      </button>
      {/* Inline rather than a page-level alert: the reader needs to know which
          row failed, and a banner at the top of a list of versions does not
          say. */}
      {failed && <span className="text-xs text-red-700">Couldn&apos;t download</span>}
    </span>
  )
}
