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
 * Plain text gets its own panel. It used to fall into the Word branch and tell
 * the reader that "Word documents can't be shown in the browser… open it in
 * Word" about a `.txt` file — which is what a user saw after tailoring a resume,
 * because that produced a text version and linked them straight at it.
 *
 * **Nothing here may gain a `sandbox` attribute.** Without `allow-scripts` it
 * breaks Chrome's built-in PDF viewer, and the exposure it would mitigate is
 * already closed twice over: uploads are validated by magic bytes, so only
 * genuine PDFs are ever stored, and useResumeFile re-wraps the blob with the
 * stored mime type before it reaches the frame.
 */

const PDF_MIME = 'application/pdf'
const TEXT_MIME = 'text/plain'

/** Tall enough to read, short enough that the page does not scroll to reach it. */
const FRAME_HEIGHT = 'h-[60vh] sm:h-[75vh]'

export function ResumeFilePreview({
  versionId,
  mimeType,
  filename,
  fileSizeBytes,
  rawText,
}: {
  versionId: string
  mimeType: string
  filename: string
  fileSizeBytes: number
  /**
   * The version's text, when the page already has it.
   *
   * Supplied so the text can be offered as a `.txt` download without a second
   * request: it is the same text the stored document was rendered from, so the
   * two formats agree by construction rather than by coincidence.
   */
  rawText?: string | null
}) {
  const isPdf = mimeType === PDF_MIME
  const isText = mimeType === TEXT_MIME
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

  // Built here rather than fetched: `rawText` is what the stored document was
  // rendered from, so this is the same words without a round trip.
  const textButton =
    rawText === null || rawText === undefined || rawText === '' ? null : (
      <Button
        variant="secondary"
        size="sm"
        onClick={() =>
          saveBlob(
            new Blob([rawText], { type: 'text/plain;charset=utf-8' }),
            `${filename.replace(/\.[^.]+$/, '')}.txt`,
          )
        }
      >
        Download .txt
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
        <div className="flex flex-wrap gap-2">
          {downloadButton}
          {textButton}
        </div>
      </div>

      {downloadFailed && (
        <Alert tone="error">We couldn&apos;t download that file. Please try again.</Alert>
      )}

      {isText ? (
        // Shown, not described. The text is right here, so a panel explaining
        // that it cannot be displayed would be both wrong and unhelpful.
        <pre
          className={`${FRAME_HEIGHT} overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs whitespace-pre-wrap text-slate-700`}
        >
          {rawText ?? ''}
        </pre>
      ) : !isPdf ? (
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
