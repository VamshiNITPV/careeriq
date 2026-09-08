import { useCallback, useEffect, useState } from 'react'
import { resumeService } from '@/services/resumeService'

/**
 * Fetch a stored resume file and hand back a URL the browser can render.
 *
 * **Why a fetch rather than a link.** `GET /resumes/versions/{id}/download`
 * needs an `Authorization` header, and neither a browser navigation nor an
 * `<iframe src>` sends one — both would simply 401. There are no signed URLs to
 * fall back on. So the bytes come through the authenticated client and become a
 * `blob:` URL here.
 *
 * A hook rather than component-local state so the preview and the Download
 * button share one blob instead of fetching the same file twice.
 */

export type FilePreviewState = 'idle' | 'loading' | 'ready' | 'error'

interface UseResumeFile {
  state: FilePreviewState
  /** An object URL, live only while this hook is mounted with this versionId. */
  url: string | null
  blob: Blob | null
  reload: () => void
}

export function useResumeFile(
  versionId: string | null,
  mimeType: string,
  { enabled }: { enabled: boolean },
): UseResumeFile {
  const [state, setState] = useState<FilePreviewState>('idle')
  const [url, setUrl] = useState<string | null>(null)
  const [blob, setBlob] = useState<Blob | null>(null)
  const [attempt, setAttempt] = useState(0)

  const reload = useCallback(() => setAttempt((n) => n + 1), [])

  useEffect(() => {
    if (!enabled || versionId === null) return

    let cancelled = false
    // Held in the closure rather than in state, because the cleanup below must
    // be able to revoke it without depending on a render having happened.
    let created: string | null = null

    setState('loading')

    resumeService.downloadFile(versionId).then(
      (fetched) => {
        // Checked BEFORE createObjectURL, and that ordering is the whole point.
        // Creating the URL first and bailing afterwards *is* the leak: the
        // cleanup has already run by then, closing over a `created` that was
        // still null, so nothing ever revokes it.
        if (cancelled) return

        // Re-wrapped when the server's Content-Type did not survive the trip.
        // Cheap at 5MB, and it is what makes the browser route a PDF to its
        // viewer rather than offering a surprise download.
        const typed = fetched.type === mimeType ? fetched : new Blob([fetched], { type: mimeType })
        created = URL.createObjectURL(typed)
        setBlob(typed)
        setUrl(created)
        setState('ready')
      },
      () => {
        if (!cancelled) setState('error')
      },
    )

    return () => {
      cancelled = true
      // Keyed on versionId, so switching versions revokes the previous URL here
      // rather than needing teardown of its own. Without this, every navigation
      // strands a copy of the file in memory until the page is reloaded — on a
      // phone that is a crash, not a theoretical leak.
      if (created !== null) URL.revokeObjectURL(created)
    }
  }, [versionId, mimeType, enabled, attempt])

  return { state, url, blob, reload }
}

/**
 * Save a blob to disk under a chosen name.
 *
 * Its own object URL with a matching revoke, deliberately separate from the
 * preview's: the download must work on the Word path, where nothing is fetched
 * for display and there is no preview URL to borrow.
 */
export function saveBlob(blob: Blob, filename: string): void {
  const href = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // Deferred: revoking synchronously can cancel the download in some browsers
  // before it has read the URL.
  setTimeout(() => URL.revokeObjectURL(href), 0)
}
