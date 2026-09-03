import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { SkillAdder } from '@/components/SkillAdder'
import { Alert } from '@/components/ui/Alert'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
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
  type SuggestedSkill,
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
  const [suggestions, setSuggestions] = useState<SuggestedSkill[]>([])
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [suggestionVersionId, setSuggestionVersionId] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Resume | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
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

    // Suggestions belong to the primary resume's current version. Fetched
    // separately and tolerantly: a failure here must not blank the page, since
    // suggestions are an extra rather than the point of it.
    const primary = resumeList.find((r) => r.is_primary) ?? resumeList[0]
    if (primary?.current_version_id != null) {
      try {
        const result = await resumeService.suggestions(primary.current_version_id)
        setSuggestions(result.suggestions)
        setSuggestionVersionId(result.version_id)
      } catch {
        setSuggestions([])
        setSuggestionVersionId(null)
      }
    } else {
      setSuggestions([])
      setSuggestionVersionId(null)
    }
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

  // Dismissals are local to the session on purpose: persisting "never suggest
  // this again" is a preference worth designing properly rather than inferring
  // from one click.
  const visibleSuggestions = suggestions.filter((s) => !dismissed.has(s.name))

  async function confirmDelete() {
    if (pendingDelete === null) return
    setIsDeleting(true)
    try {
      await resumeService.remove(pendingDelete.id)
      await refresh()
      setPendingDelete(null)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : 'Could not delete that resume.')
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <div className="space-y-8">
      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete “${pendingDelete?.title ?? ''}”?`}
        confirmLabel="Delete resume"
        destructive
        isBusy={isDeleting}
        onConfirm={() => void confirmDelete()}
        onCancel={() => {
          if (!isDeleting) setPendingDelete(null)
        }}
      >
        {/* States the consequence in numbers. "Are you sure?" tells the user
            nothing they did not already know; what they cannot see is how much
            of their profile is about to go with the file. */}
        <p>This cannot be undone.</p>
        {pendingDelete !== null && pendingDelete.skill_count > 0 && (
          <p className="mt-2">
            <strong>{pendingDelete.skill_count} skills</strong> came from this resume and will be
            removed with it. Skills you typed in yourself are kept.
          </p>
        )}
      </ConfirmDialog>

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
                  onClick={() => setPendingDelete(resume)}
                >
                  Delete
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ------------------------------------------------------ suggestions */}
      {visibleSuggestions.length > 0 && (
        <section aria-labelledby="suggested-heading">
          <h2 id="suggested-heading" className="text-base font-semibold text-slate-900">
            Suggested from your experience{' '}
            <span className="text-slate-400">({visibleSuggestions.length})</span>
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            {/* Stated plainly. These are the system's reading of the resume,
                not something the candidate wrote, and presenting them as
                findings would be putting words in their mouth. */}
            Your resume describes these but doesn&apos;t name them. They are{' '}
            <strong>not on your profile</strong> — add only the ones you would be
            comfortable discussing in an interview.
          </p>

          <ul className="mt-3 space-y-2">
            {visibleSuggestions.map((suggestion) => (
              <li
                key={suggestion.name}
                className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200"
              >
                <div className="flex flex-wrap items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-slate-900">{suggestion.name}</p>
                    {/* The evidence is the whole point: the user judges the
                        reasoning, not a bare label. */}
                    <p className="mt-1 border-l-2 border-slate-200 pl-3 text-sm text-slate-600 italic">
                      “{suggestion.evidence}”
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button
                      size="sm"
                      disabled={suggestion.skill_id === null}
                      onClick={() => {
                        const id = suggestion.skill_id
                        if (id === null || suggestionVersionId === null) return
                        // Linked to the resume it was suggested from, so it is
                        // removed with that resume rather than outliving it.
                        void skillService.add(id, suggestionVersionId).then(() => {
                          setDismissed((prev) => new Set(prev).add(suggestion.name))
                          void refresh()
                        })
                      }}
                    >
                      Add
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        setDismissed((prev) => new Set(prev).add(suggestion.name))
                      }
                    >
                      Dismiss
                    </Button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* ------------------------------------------------------ skills */}
      <section aria-labelledby="skills-heading">
        <h2 id="skills-heading" className="text-base font-semibold text-slate-900">
          Extracted skills{' '}
          {skills.length > 0 && <span className="text-slate-400">({skills.length})</span>}
        </h2>

        {skills.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">
            Upload a resume, or add skills by hand below.
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

        <div className="mt-6 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
          <SkillAdder onAdded={() => void refresh()} />
        </div>
      </section>
    </div>
  )
}
