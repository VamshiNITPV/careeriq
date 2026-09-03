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

/**
 * One shape for every failure on this page.
 *
 * `title` names the action, which is what makes a single alert at the top
 * legible for a click that happened at the bottom — "Couldn't remove that
 * skill" rather than a bare server message with no context.
 */
interface PageError {
  title: string
  message: string
  correlationId?: string | undefined
}

function toPageError(caught: unknown, title: string, fallback: string): PageError {
  return caught instanceof ApiError
    ? { title, message: caught.message, correlationId: caught.correlationId }
    : { title, message: fallback }
}

function messageOf(caught: unknown, fallback: string): string {
  return caught instanceof ApiError ? caught.message : fallback
}

function SkillChip({
  skill,
  onRemove,
  isBusy,
  disabled,
}: {
  skill: CandidateSkill
  onRemove: () => void
  isBusy: boolean
  disabled: boolean
}) {
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
        // A raw button, so it gets none of Button's built-in busy handling.
        disabled={disabled || isBusy}
        aria-busy={isBusy}
        aria-label={`Remove ${skill.skill.name}`}
        className="rounded-full px-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        ×
      </button>
    </span>
  )
}

/** Statuses that mean the server is still working on this resume. */
const IN_FLIGHT = ['PENDING', 'EXTRACTING', 'PARSING', 'EMBEDDING']

export function ResumePage() {
  const [resumes, setResumes] = useState<Resume[]>([])
  const [skills, setSkills] = useState<CandidateSkill[]>([])
  const [suggestions, setSuggestions] = useState<SuggestedSkill[]>([])
  const [suggestionsFailed, setSuggestionsFailed] = useState(false)
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [suggestionVersionId, setSuggestionVersionId] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Resume | null>(null)
  const [error, setError] = useState<PageError | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  // Rendered inside the dialog, not at the top of the page: ConfirmDialog uses
  // showModal(), which makes the rest of the document inert — so a page-level
  // alert about a failed delete sits behind the backdrop, invisible.
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading')
  /**
   * Which single action is in flight, if any.
   *
   * One key rather than a set: every mutation ends in a full `refresh()` that
   * rewrites resumes, skills and suggestions wholesale, so two overlapping
   * mutations produce two overlapping refreshes whose responses can land out of
   * order — and the stale one wins. A single string makes that impossible.
   */
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const requestId = useRef(0)

  const { progress, phase, track, retry, reset } = useResumeProcessing()

  const refresh = useCallback(async () => {
    // Guards against an out-of-order landing. The poll's own onDone → refresh()
    // is not user-triggered, so busyKey cannot serialise it against a manual
    // action, and without this a just-removed skill can reappear.
    const id = ++requestId.current

    const [resumeList, skillList] = await Promise.all([
      resumeService.list(),
      skillService.mySkills(),
    ])
    if (id !== requestId.current) return
    setResumes(resumeList)
    setSkills(skillList)

    // Suggestions belong to the primary resume's current version. Fetched
    // separately and tolerantly: a failure here must not blank the page, since
    // suggestions are an extra rather than the point of it.
    const primary = resumeList.find((r) => r.is_primary) ?? resumeList[0]
    if (primary?.current_version_id != null) {
      try {
        const result = await resumeService.suggestions(primary.current_version_id)
        if (id !== requestId.current) return
        setSuggestions(result.suggestions)
        setSuggestionVersionId(result.version_id)
        setSuggestionsFailed(false)
      } catch {
        if (id !== requestId.current) return
        setSuggestions([])
        setSuggestionVersionId(null)
        // Tracked separately so a 500 does not present as "the parser found
        // nothing", which is what an empty list silently looks like.
        setSuggestionsFailed(true)
      }
    } else {
      setSuggestions([])
      setSuggestionVersionId(null)
      setSuggestionsFailed(false)
    }
  }, [])

  const load = useCallback(() => {
    setLoadState('loading')
    setError(null)
    refresh().then(
      () => setLoadState('ready'),
      (caught: unknown) => {
        // Without this the page reported "Nothing uploaded yet." for a network
        // blip — telling the user their resumes were gone.
        setError(toPageError(caught, "We couldn't load your resumes", 'Please try again.'))
        setLoadState('error')
      },
    )
  }, [refresh])

  useEffect(load, [load])

  /**
   * Every mutation goes through here, so clearing, busy state and error capture
   * are decided in one place rather than six.
   */
  const run = useCallback(
    async (key: string, title: string, fallback: string, action: () => Promise<void>) => {
      if (busyKey !== null) return
      setBusyKey(key)
      setError(null)
      setNotice(null)
      // Drop a finished banner so the page never congratulates the user on a
      // parse while they are doing something else. Guarded on 'settled' so it
      // cannot cancel a poll that is still running.
      if (phase === 'settled') reset()

      try {
        await action()
      } catch (caught) {
        setError(toPageError(caught, title, fallback))
        setBusyKey(null)
        return
      }

      // A separate try: the action succeeded, and reporting "Couldn't remove
      // that skill" because the *refresh* failed would tell the user the
      // opposite of what happened.
      try {
        await refresh()
      } catch {
        setError({
          title: 'That worked, but this page is out of date',
          message: 'Reload to see the latest.',
        })
      } finally {
        setBusyKey(null)
      }
    },
    [busyKey, phase, refresh, reset],
  )

  const handleFile = useCallback(
    async (file: File) => {
      if (busyKey !== null) return
      setError(null)
      setNotice(null)
      reset()

      const localError = localFileError(file)
      if (localError !== undefined) {
        setError({ title: "We can't use that file", message: localError })
        return
      }

      setBusyKey('upload')
      try {
        const result = await resumeService.upload(file)

        if (result.is_duplicate) {
          // The server reused an earlier parse, so there is nothing to poll.
          // Said out loud: previously this branch changed nothing on screen and
          // the upload looked like it had silently failed.
          setNotice(
            "You've already uploaded that file. We reused the skills we pulled from it the " +
              'first time, so there was nothing new to process.',
          )
          await refresh()
          return
        }

        track(result.version_id, () => {
          void refresh()
        })
      } catch (caught) {
        setError(
          toPageError(
            caught,
            "We couldn't upload that file",
            'Upload failed. Please check your connection and try again.',
          ),
        )
      } finally {
        setBusyKey(null)
      }
    },
    [busyKey, refresh, reset, track],
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

  const isPolling = phase === 'polling'
  // Covers the gap between the 202 and the first status response. Without it
  // the panel drops back to "Drag a file here" for a whole round trip and
  // visibly forgets the file that was just uploaded.
  const showProcessing = busyKey === 'upload' || isPolling
  const locked = busyKey !== null || isPolling

  // Dismissals are local to the session on purpose: persisting "never suggest
  // this again" is a preference worth designing properly rather than inferring
  // from one click.
  const visibleSuggestions = suggestions.filter((s) => !dismissed.has(s.name))

  async function confirmDelete() {
    if (pendingDelete === null || busyKey !== null) return
    const target = pendingDelete
    setDeleteError(null)
    setBusyKey(`delete:${target.id}`)
    try {
      await resumeService.remove(target.id)
      setPendingDelete(null)
      await refresh()
    } catch (caught) {
      setDeleteError(messageOf(caught, 'Could not delete that resume.'))
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <div className="space-y-8">
      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete “${pendingDelete?.title ?? ''}”?`}
        confirmLabel="Delete resume"
        destructive
        isBusy={busyKey === `delete:${pendingDelete?.id ?? ''}`}
        onConfirm={() => void confirmDelete()}
        onCancel={() => {
          if (busyKey === null) {
            setPendingDelete(null)
            setDeleteError(null)
          }
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
        {deleteError !== null && (
          <p role="alert" className="mt-3 rounded-md bg-red-50 p-2 text-sm text-red-700">
            {deleteError}
          </p>
        )}
      </ConfirmDialog>

      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Resume</h1>
        <p className="mt-1 text-sm text-slate-600">
          Upload a PDF or DOCX and we&apos;ll pull out your skills automatically.
        </p>
      </div>

      {error !== null && (
        <Alert tone="error" title={error.title} correlationId={error.correlationId}>
          {error.message}
        </Alert>
      )}
      {notice !== null && <Alert tone="info">{notice}</Alert>}

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

        {showProcessing ? (
          <div className="space-y-3">
            <Spinner className="mx-auto size-8 text-indigo-600" label="Processing your resume" />
            <p className="text-sm font-medium text-slate-900">
              {progress?.stage_label ?? 'Uploading'}…
            </p>
            <div
              className="mx-auto h-2 w-full max-w-sm overflow-hidden rounded-full bg-slate-200"
              role="progressbar"
              aria-valuenow={progress?.percent ?? 0}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Resume processing progress"
            >
              <div
                className="h-full bg-indigo-600 transition-all duration-500"
                style={{ width: `${progress?.percent ?? 0}%` }}
              />
            </div>
          </div>
        ) : (
          <>
            <p className="text-sm text-slate-600">Drag a file here, or</p>
            <Button className="mt-3" disabled={locked} onClick={() => inputRef.current?.click()}>
              Choose a file
            </Button>
            <p className="mt-3 text-xs text-slate-500">
              PDF or DOCX, up to {formatFileSize(MAX_UPLOAD_BYTES)}
            </p>
          </>
        )}
      </section>

      {progress?.status === 'FAILED' && (
        // A terminal failure states the reason, so the user knows whether to
        // retry or upload something different (US-2.2 AC2). The fallback is not
        // hypothetical — the pipeline has paths that reach FAILED without ever
        // writing a message to the row.
        <Alert tone="error" title="We couldn't read that file">
          {progress.error ??
            'Something went wrong reading this document. Try uploading it again, or try a ' +
              'different file.'}
        </Alert>
      )}

      {phase === 'timedOut' && (
        <Alert tone="warning" title="Still working on it">
          <p>
            We&apos;ve stopped checking for now — the parse may still be finishing in the
            background.
          </p>
          <Button variant="secondary" size="sm" className="mt-3" onClick={retry}>
            Check again
          </Button>
        </Alert>
      )}

      {phase === 'settled' && progress?.status === 'COMPLETE' && (
        <Alert tone="success">Resume processed. Your skills are below.</Alert>
      )}

      {/* ------------------------------------------------------ resumes */}
      <section aria-labelledby="resumes-heading">
        <h2 id="resumes-heading" className="text-base font-semibold text-slate-900">
          Your resumes
        </h2>

        {loadState === 'loading' ? (
          <Spinner className="mt-4 size-5 text-slate-400" label="Loading" />
        ) : loadState === 'error' ? (
          <Button variant="secondary" size="sm" className="mt-3" onClick={load}>
            Try again
          </Button>
        ) : resumes.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">Nothing uploaded yet.</p>
        ) : (
          <ul className="mt-3 divide-y divide-slate-200 overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
            {resumes.map((resume) => {
              const status = resume.latest_version_status
              const rowFailed = status === 'FAILED'
              const rowProcessing = status !== null && IN_FLIGHT.includes(status)
              const versionId = resume.latest_version_id

              return (
                <li key={resume.id} className="flex items-center gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-slate-900">{resume.title}</p>
                    <p className="text-xs text-slate-500">
                      Added {new Date(resume.created_at).toLocaleDateString()}
                    </p>
                    {/* Without this a resume whose parse failed reads exactly
                        like a healthy one, and the user has no idea why it
                        contributed no skills. */}
                    {rowFailed && resume.latest_version_error !== null && (
                      <p className="mt-1 text-xs text-red-600">{resume.latest_version_error}</p>
                    )}
                  </div>

                  {rowFailed && (
                    <span className="shrink-0 rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">
                      Couldn&apos;t be read
                    </span>
                  )}
                  {rowProcessing && (
                    <span className="shrink-0 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                      Processing…
                    </span>
                  )}
                  {resume.is_primary && !rowFailed && !rowProcessing && (
                    <span className="shrink-0 rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
                      Primary
                    </span>
                  )}

                  {versionId !== null && (
                    // Targets the *latest* version, not the current one: for
                    // "try again" that is the file that failed, and for
                    // "re-extract" it is the newest file uploaded. Gating this
                    // on current_version_id, as it used to, hid the button
                    // precisely when it was needed — a failed parse never
                    // becomes current, so the only recovery was delete and
                    // re-upload.
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={locked || rowProcessing}
                      isLoading={busyKey === `reparse:${versionId}`}
                      onClick={() =>
                        void run(
                          `reparse:${versionId}`,
                          "We couldn't start that again",
                          'Please try again.',
                          async () => {
                            const result = await resumeService.reparse(versionId)
                            track(result.version_id, () => void refresh())
                          },
                        )
                      }
                    >
                      {rowFailed ? 'Try again' : 'Re-extract'}
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={locked}
                    onClick={() => {
                      setDeleteError(null)
                      setPendingDelete(resume)
                    }}
                  >
                    Delete
                  </Button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {/* ------------------------------------------------------ suggestions */}
      {loadState === 'ready' && suggestionsFailed && (
        <p className="text-sm text-slate-500">
          Couldn&apos;t load suggested skills.{' '}
          <button
            type="button"
            onClick={() => void refresh()}
            className="font-medium text-indigo-600 underline hover:text-indigo-700"
          >
            Try again
          </button>
        </p>
      )}

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
            <strong>not on your profile</strong> — add only the ones you would be comfortable
            discussing in an interview.
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
                      disabled={suggestion.skill_id === null || locked}
                      isLoading={busyKey === `suggestion:${suggestion.name}`}
                      onClick={() => {
                        const id = suggestion.skill_id
                        if (id === null || suggestionVersionId === null) return
                        void run(
                          `suggestion:${suggestion.name}`,
                          "We couldn't add that skill",
                          'Please try again.',
                          async () => {
                            // Linked to the resume it was suggested from, so it
                            // is removed with that resume rather than outliving
                            // it.
                            await skillService.add(id, suggestionVersionId)
                            // Inside the action, so a failed add leaves the
                            // suggestion on screen instead of quietly
                            // dismissing it.
                            setDismissed((prev) => new Set(prev).add(suggestion.name))
                          },
                        )
                      }}
                    >
                      Add
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={locked}
                      onClick={() => setDismissed((prev) => new Set(prev).add(suggestion.name))}
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

        {loadState !== 'ready' ? (
          // Gated on the load, like the resumes section above. Ungated, a
          // returning user with forty skills was told to go upload a resume on
          // every single visit, for as long as the fetch took.
          <Spinner className="mt-4 size-5 text-slate-400" label="Loading" />
        ) : skills.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">
            Upload a resume, or add skills by hand below.
          </p>
        ) : (
          <div className="mt-3 flex flex-wrap gap-2">
            {skills.map((skill) => (
              <SkillChip
                key={skill.id}
                skill={skill}
                isBusy={busyKey === `skill:${skill.id}`}
                disabled={locked}
                onRemove={() =>
                  void run(
                    `skill:${skill.id}`,
                    "We couldn't remove that skill",
                    'Please try again.',
                    async () => {
                      await skillService.remove(skill.id)
                    },
                  )
                }
              />
            ))}
          </div>
        )}

        <div className="mt-6 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
          {/* Routed through refresh's own error path rather than a bare
              `void refresh()`, which was a fourth unhandled rejection. */}
          <SkillAdder
            onAdded={() => {
              refresh().catch(() =>
                setError({
                  title: 'That worked, but this page is out of date',
                  message: 'Reload to see the latest.',
                }),
              )
            }}
          />
        </div>
      </section>
    </div>
  )
}
