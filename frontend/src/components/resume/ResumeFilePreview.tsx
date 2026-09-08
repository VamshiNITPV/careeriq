import { useState } from 'react'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { saveBlob, useResumeFile } from '@/hooks/useResumeFile'
import { resumeService } from '@/services/resumeService'
import { formatFileSize } from '@/types/resume'

/**
 * The uploaded document itself.
 *
 * PDFs render in an `<iframe>` pointed at a `blob:` URL. Word documents do not
 * render in any browser, so those get a panel saying so and a download instead
 * — converting them server-side would mean carrying LibreOffice in the image.
 *
 * **Nothing here may gain a `sandbox` attribute.** Without `allow-scripts` it
 * breaks Chrome's built-in PDF viewer, and the exposure it would mitigate is
 * already closed twice over: uploads are validated by magic bytes, so only
 * genuine PDFs are ever stored, and useResumeFile re-wraps the blob with the
 * stored mime type before it reaches the frame.
 */

const PDF_MIME = 'application/pdf'

/** Tall enough to read, short enough that the page does not scroll to reach it. */
const FRAME_HEIGHT = 'h-[60vh] sm:h-[75vh]'

export function ResumeFilePreview({
  versionId,
  mimeType,
  filename,
  fileSizeBytes,
}: {
  versionId: string
  mimeType: string
  filename: string
  fileSizeBytes: number
}) {
  const isPdf = mimeType === PDF_MIME
  // Word files are never fetched for display — pulling megabytes down to render
  // nothing is pure waste. They are fetched only when Download is pressed.
  const file = useResumeFile(versionId, mimeType, { enabled: isPdf })
  const [isDownloading, setIsDownloading] = useState(false)
  const [downloadFailed, setDownloadFailed] = useState(false)

  async function download() {
    setDownloadFailed(false)
    if (file.blob !== null) {
      saveBlob(file.blob, filename)
      return
    }
    setIsDownloading(true)
    try {
      saveBlob(await resumeService.downloadFile(versionId), filename)
    } catch {
      setDownloadFailed(true)
    } finally {
      setIsDownloading(false)
    }
  }

  const downloadButton = (
    <Button variant="secondary" size="sm" isLoading={isDownloading} onClick={() => void download()}>
      Download
    </Button>
  )

  return (
    <section aria-labelledby="document-heading" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 id="document-heading" className="truncate text-base font-semibold text-slate-900">
            {filename}
          </h2>
          <p className="text-xs text-slate-500">{formatFileSize(fileSizeBytes)}</p>
        </div>
        {downloadButton}
      </div>

      {downloadFailed && (
        <Alert tone="error">We couldn&apos;t download that file. Please try again.</Alert>
      )}

      {!isPdf ? (
        <div
          className={`flex ${FRAME_HEIGHT} flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-center`}
        >
          <p className="text-sm font-medium text-slate-900">
            Word documents can&apos;t be shown in the browser.
          </p>
          <p className="max-w-sm text-sm text-slate-600">
            Everything we read from it is below. Download the file to open it in Word.
          </p>
          {downloadButton}
        </div>
      ) : file.state === 'error' ? (
        <div
          className={`flex ${FRAME_HEIGHT} flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-center`}
        >
          <p className="text-sm font-medium text-slate-900">We couldn&apos;t show this file.</p>
          <div className="flex gap-3">
            <Button variant="secondary" size="sm" onClick={file.reload}>
              Try again
            </Button>
            {downloadButton}
          </div>
        </div>
      ) : file.url === null ? (
        // The height is kept while loading on purpose. Collapsing to nothing and
        // then jumping to full height reflows everything below it.
        <div
          className={`flex ${FRAME_HEIGHT} items-center justify-center rounded-lg border border-slate-200 bg-slate-100`}
        >
          <Spinner className="size-6 text-slate-400" label="Loading the document" />
        </div>
      ) : (
        // An <iframe> rather than <object> or <embed>: only this one takes a
        // title, which is both its accessible name and how a test finds it.
        <iframe
          src={file.url}
          title={`Preview of ${filename}`}
          className={`${FRAME_HEIGHT} w-full rounded-lg border border-slate-200 bg-slate-100`}
        />
      )}
    </section>
  )
}
