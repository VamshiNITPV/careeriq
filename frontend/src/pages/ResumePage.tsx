import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { useResumeProcessing } from '@/hooks/useResumeProcessing'
import { ApiError } from '@/services/apiClient'
import { resumeService, skillService } from '@/services/resumeService'
import {
  ACCEPTED_MIME_TYPES,
  MAX_UPLOAD_BYTES,
  formatFileSize,
  type CandidateSkill,
  type Resume,
} from '@/types/resume'
import { cn } from '@/utils/cn'

/**
 * Client-side pre-check.
 *
 * Convenience only — the server validates by reading the file's bytes, which is
 * the check that matters, because anything here can be bypassed. This exists so
 * the obvious mistakes fail instantly instead of after a 5 MB upload.
 */
function localFileError(file: File): string | undefined {
  if (file.size === 0) return 'That file is empty.'
  if (file.size > MAX_UPLOAD_BYTES) {
    return `That file is ${formatFileSize(file.size)}. The maximum is ${formatFileSize(MAX_UPLOAD_BYTES)}.`
  }
  const name = file.name.toLowerCase()
  const looksRight =
    (ACCEPTED_MIME_TYPES as readonly string[]).includes(file.type) ||
    name.endsWith('.pdf') ||
    name.endsWith('.docx')
  if (!looksRight) return 'Please choose a PDF or DOCX file.'
  return undefined
}

function SkillChip({ skill, onRemove }: { skill: CandidateSkill; onRemove: () => void }) {
  const confidence =
    skill.extraction_confidence !== null ? Number(skill.extraction_confidence) : null

  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-white py-1 pr-1 pl-3 text-sm ring-1 ring-slate-300 ring-inset">
      {skill.skill.name}
      {skill.is_user_verified ? (
        <span className="text-xs text-emerald-600" title="Added or confirmed by you">
          ✓
        </span>
      ) : (
        confidence !== null && (
          // Shown so the user can see which entries the parser was less sure
          // about, rather than presenting every extraction as equally certain.
          <span className="text-xs text-slate-400" title="Extraction confidence">
            {Math.round(confidence * 100)}%
          </span>
        )
      )}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${skill.skill.name}`}
        className="rounded-full px-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
      >
        ×
      </button>
    </span>
  )
}

export function ResumePage() {
  const [resumes, setResumes] = useState<Resume[]>([])
  const [skills, setSkills] = useState<CandidateSkill[]>([])
  const [error, setError] = useState<ApiError | string | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const { progress, timedOut, track, reset } = useResumeProcessing()

  const refresh = useCallback(async () => {
    const [resumeList, skillList] = await Promise.all([
      resumeService.list(),
      skillService.mySkills(),
    ])
    setResumes(resumeList)
    setSkills(skillList)
  }, [])

  useEffect(() => {
    void refresh().finally(() => setLoaded(true))
  }, [refresh])

  const handleFile = useCallback(
    async (file: File) => {
      setError(null)
      reset()

      const localError = localFileError(file)
      if (localError !== undefined) {
        setError(localError)
        return
      }

      setIsUploading(true)
      try {
        const result = await resumeService.upload(file)

        if (result.is_duplicate) {
          // The server reused an earlier parse, so there is nothing to poll.
          await refresh()
          return
        }

        track(result.version_id, () => {
          void refresh()
        })
      } catch (caught) {
        setError(
          caught instanceof ApiError
            ? caught
            : 'Upload failed. Please check your connection and try again.',
        )
      } finally {
        setIsUploading(false)
      }
    },
    [refresh, reset, track],
  )

  function onInputChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (file) void handleFile(file)
    // Reset so selecting the same file again still fires a change event.
    event.target.value = ''
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setIsDragging(false)
    const file = event.dataTransfer.files[0]
    if (file) void handleFile(file)
  }

  const isProcessing = progress !== null && !progress.is_terminal
  const failed = progress?.status === 'FAILED'

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Resume</h1>
        <p className="mt-1 text-sm text-slate-600">
          Upload a PDF or DOCX and we&apos;ll pull out your skills automatically.
        </p>
      </div>

      {typeof error === 'string' && <Alert tone="error">{error}</Alert>}
      {error instanceof ApiError && (
        <Alert tone="error" correlationId={error.correlationId}>
          {error.message}
        </Alert>
      )}

      {/* ------------------------------------------------------ upload */}
      <section
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragging(true)
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        className={cn(
          'rounded-lg border-2 border-dashed p-8 text-center transition-colors',
          isDragging ? 'border-indigo-500 bg-indigo-50' : 'border-slate-300 bg-white',
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          onChange={onInputChange}
          className="sr-only"
          id="resume-file"
        />

        {isProcessing ? (
          <div className="space-y-3">
            <Spinner className="mx-auto size-8 text-indigo-600" label="Processing your resume" />
            <p className="text-sm font-medium text-slate-900">{progress.stage_label}…</p>
            <div
              className="mx-auto h-2 w-full max-w-sm overflow-hidden rounded-full bg-slate-200"
              role="progressbar"
              aria-valuenow={progress.percent}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Resume processing progress"
            >
              <div
                className="h-full bg-indigo-600 transition-all duration-500"
                style={{ width: `${progress.percent}%` }}
              />
            </div>
          </div>
        ) : (
          <>
            <p className="text-sm text-slate-600">Drag a file here, or</p>
            <Button
              className="mt-3"
              isLoading={isUploading}
              onClick={() => inputRef.current?.click()}
            >
              Choose a file
            </Button>
            <p className="mt-3 text-xs text-slate-500">
              PDF or DOCX, up to {formatFileSize(MAX_UPLOAD_BYTES)}
            </p>
          </>
        )}
      </section>

      {failed && progress.error !== null && (
        // A terminal failure states the reason, so the user knows whether to
        // retry or upload something different (US-2.2 AC2).
        <Alert tone="error" title="We couldn't read that file">
          {progress.error}
        </Alert>
      )}

      {timedOut && (
        <Alert tone="warning">
          Processing is taking longer than expected. Refresh the page to check again.
        </Alert>
      )}

      {progress?.status === 'COMPLETE' && (
        <Alert tone="success">Resume processed. Your skills are below.</Alert>
      )}

      {/* ------------------------------------------------------ resumes */}
      <section aria-labelledby="resumes-heading">
        <h2 id="resumes-heading" className="text-base font-semibold text-slate-900">
          Your resumes
        </h2>

        {!loaded ? (
          <Spinner className="mt-4 size-5 text-slate-400" label="Loading" />
        ) : resumes.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">Nothing uploaded yet.</p>
        ) : (
          <ul className="mt-3 divide-y divide-slate-200 overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
            {resumes.map((resume) => (
              <li key={resume.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-900">{resume.title}</p>
                  <p className="text-xs text-slate-500">
                    Added {new Date(resume.created_at).toLocaleDateString()}
                  </p>
                </div>
                {resume.is_primary && (
                  <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
                    Primary
                  </span>
                )}
                {resume.current_version_id !== null && (
                  // The taxonomy keeps growing, so a resume parsed earlier was
                  // parsed by an older extractor. Re-extracting picks up newly
                  // recognised skills without needing the file uploaded again.
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      const versionId = resume.current_version_id
                      if (versionId === null) return
                      void resumeService.reparse(versionId).then((result) => {
                        track(result.version_id, () => void refresh())
                      })
                    }}
                  >
                    Re-extract
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    void resumeService.remove(resume.id).then(refresh)
                  }}
                >
                  Delete
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ------------------------------------------------------ skills */}
      <section aria-labelledby="skills-heading">
        <h2 id="skills-heading" className="text-base font-semibold text-slate-900">
          Extracted skills{' '}
          {skills.length > 0 && <span className="text-slate-400">({skills.length})</span>}
        </h2>

        {skills.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">
            Upload a resume and your skills will appear here.
          </p>
        ) : (
          <div className="mt-3 flex flex-wrap gap-2">
            {skills.map((skill) => (
              <SkillChip
                key={skill.id}
                skill={skill}
                onRemove={() => {
                  void skillService.remove(skill.id).then(refresh)
                }}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
