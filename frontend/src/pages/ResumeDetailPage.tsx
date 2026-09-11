import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ResumeFilePreview } from '@/components/resume/ResumeFilePreview'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { buttonClass } from '@/components/ui/buttonStyles'
import { Input } from '@/components/ui/Input'
import { Spinner } from '@/components/ui/Spinner'
import { ApiError } from '@/services/apiClient'
import { careerService } from '@/services/careerService'
import { resumeService } from '@/services/resumeService'
import { formatSpan, type CareerSummary } from '@/types/career'
import {
  formatFileSize,
  IN_FLIGHT,
  type Resume,
  type ResumeDetail,
  type ResumeVersionDetail,
} from '@/types/resume'
import { formatDateTime } from '@/utils/datetime'

/**
 * One resume: the document, and what the parser made of it.
 *
 * Almost everything here was already served and never asked for —
 * `GET /resumes/{id}` and `GET /resumes/versions/{id}` both predate this page.
 *
 * The organising question is "did it read my document properly, and what did it
 * do with the result", which is why the page shows sections found and skills
 * found rather than every key in the stored JSON. Parser diagnostics, the
 * extracted contact details (already visible on the profile, and re-rendering
 * them here would be fresh exposure of the same PII) and the entity counts
 * recorded at parse time are all deliberately left out — that last one because
 * it would contradict the live list below it the moment the user deleted a row.
 */

function Chip({ children, muted = false }: { children: React.ReactNode; muted?: boolean }) {
  return (
    <span
      className={
        muted
          ? 'rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500'
          : 'rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700'
      }
    >
      {children}
    </span>
  )
}

function Section({
  title,
  hint,
  children,
}: {
  title: string
  // `| undefined` explicitly: under exactOptionalPropertyTypes a caller passing
  // a conditionally-built value passes the property as `string | undefined`,
  // which a bare `hint?: string` rejects.
  hint?: string | undefined
  children: React.ReactNode
}) {
  return (
    <section className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      {hint !== undefined && <p className="mt-1 text-sm text-slate-600">{hint}</p>}
      <div className="mt-3">{children}</div>
    </section>
  )
}

export function ResumeDetailPage() {
  const { resumeId } = useParams<{ resumeId: string }>()
  const [searchParams] = useSearchParams()

  const [detail, setDetail] = useState<ResumeDetail | null>(null)
  const [version, setVersion] = useState<ResumeVersionDetail | null>(null)
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)

  // Its own state, fetched tolerantly: a failure here must not blank a page
  // whose main subject loaded fine.
  const [career, setCareer] = useState<CareerSummary | null>(null)
  const [careerFailed, setCareerFailed] = useState(false)

  /*
    One key rather than two booleans, and not tidiness: rename and make-primary
    PATCH the same resource and both return a full resume. With two flags they
    could overlap, and a rename response landing after a make-primary response
    would write `is_primary: false` back over a resume that is now primary.
    A single value makes that impossible.
  */
  const [busy, setBusy] = useState<'rename' | 'primary' | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const [isRenaming, setIsRenaming] = useState(false)
  const [draft, setDraft] = useState('')
  const renameButton = useRef<HTMLButtonElement>(null)
  const returnFocus = useRef(false)

  /*
    Focus goes back to Rename after the form has closed, not in the handler that
    closes it: that button is unmounted while the form is open, so its ref is
    null until React re-renders. JobsPage can focus its trigger inline only
    because that trigger never unmounts.
  */
  useEffect(() => {
    if (isRenaming || !returnFocus.current) return
    returnFocus.current = false
    renameButton.current?.focus()
  }, [isRenaming])

  /**
   * Fold a PATCH response into the page.
   *
   * A merge rather than a reload, and it is correct rather than merely cheaper:
   * `ResumeDetail` is `Resume` plus `versions`, PATCH returns exactly a
   * `Resume`, and neither action can change a version. The derived fields
   * cannot go stale either — PATCH builds its body with the same helper and the
   * same inputs as GET does.
   *
   * Reloading would be worse than wasteful: `load` sets loadState to 'loading'
   * first, so renaming one word would blank the page to a spinner, issue two
   * requests and remount the preview, re-downloading the whole PDF.
   */
  const merge = useCallback((updated: Resume) => {
    setDetail((previous) => (previous === null ? previous : { ...previous, ...updated }))
  }, [])

  const closeRename = useCallback(() => {
    returnFocus.current = true
    setIsRenaming(false)
    setActionError(null)
  }, [])

  const saveRename = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      if (resumeId === undefined || busy !== null) return
      // Trimmed before sending, so a stray space never round-trips into the
      // database. Re-checked here rather than trusting the disabled Save
      // button: implicit form submission is suppressed by a disabled default
      // button, but that is a spec detail no reader should have to know.
      const title = draft.trim()
      if (title === '') return

      setBusy('rename')
      setActionError(null)
      try {
        merge(await resumeService.rename(resumeId, title))
        setAnnouncement(`Renamed to ${title}.`)
        closeRename()
      } catch (caught) {
        // The editor stays open with what was typed. Closing it on failure
        // would throw the user's work away, which is the worst thing an inline
        // edit can do.
        setActionError(
          caught instanceof ApiError ? caught.message : 'Could not rename this resume.',
        )
      } finally {
        setBusy(null)
      }
    },
    [resumeId, busy, draft, merge, closeRename],
  )

  const makePrimary = useCallback(async () => {
    if (resumeId === undefined || busy !== null) return
    setBusy('primary')
    setActionError(null)
    try {
      merge(await resumeService.setPrimary(resumeId))
      setAnnouncement('This is now your primary resume.')
    } catch (caught) {
      setActionError(
        caught instanceof ApiError ? caught.message : 'Could not make this your primary resume.',
      )
    } finally {
      setBusy(null)
    }
  }, [resumeId, busy, merge])

  const requestedVersion = searchParams.get('v')

  const load = useCallback(() => {
    if (resumeId === undefined) return
    setLoadState('loading')
    setError(null)

    resumeService.get(resumeId).then(
      async (result) => {
        setDetail(result)

        /*
          `latest_version_id`, not `current_version_id`.

          `current_version_id` is null for a resume whose every parse failed, and
          null while the first parse is still running — so selecting it would
          leave the page blank for exactly the resumes someone most wants to
          look at. The latest version is the file they uploaded and the one the
          status pill on the list was describing.

          A `?v=` is honoured only if it names a version this resume actually
          has. Without that check a stale or hand-typed id 404s the second
          request on a page that otherwise loaded perfectly well, which is a
          confusing half-broken state rather than an error.
        */
        const known = result.versions.some((entry) => entry.id === requestedVersion)
        const selected =
          (known ? requestedVersion : null) ??
          result.latest_version_id ??
          result.current_version_id ??
          result.versions[0]?.id ??
          null

        if (selected === null) {
          setVersion(null)
          setLoadState('ready')
          return
        }

        setVersion(await resumeService.getVersion(selected))
        setLoadState('ready')
      },
      (caught: unknown) => {
        // 404 covers a deleted resume, another user's, and a made-up id alike —
        // deliberately, so the API cannot be used to enumerate.
        setError(
          caught instanceof ApiError && caught.status === 404
            ? 'That resume no longer exists.'
            : 'Could not load this resume. Please try again.',
        )
        setLoadState('error')
      },
    )
  }, [resumeId, requestedVersion])

  useEffect(load, [load])

  useEffect(() => {
    careerService.summary().then(
      (summary) => setCareer(summary),
      () => setCareerFailed(true),
    )
  }, [])

  if (loadState === 'loading') {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="size-8 text-indigo-600" label="Loading this resume" />
      </div>
    )
  }

  if (loadState === 'error' || detail === null) {
    return (
      <div className="space-y-4">
        <Alert tone="error" title="We couldn't open this resume">
          {error ?? 'Please try again.'}
        </Alert>
        <div className="flex gap-3">
          <Button variant="secondary" size="sm" onClick={load}>
            Try again
          </Button>
          <Link to="/resume" className="self-center text-sm text-indigo-600 hover:underline">
            Back to resumes
          </Link>
        </div>
      </div>
    )
  }

  const sections = version?.parsed_sections?.sections ?? []
  const skills = [...(version?.parsed_entities?.skills ?? [])].sort(
    (a, b) => b.confidence - a.confidence,
  )
  const pages = version?.parsed_sections?.page_count
  const characters = version?.parsed_sections?.character_count
  const isProcessing = version !== null && IN_FLIGHT.includes(version.processing_status)
  const hasFailed = version?.processing_status === 'FAILED'

  const fromThisVersion = <T extends { source_version_id: string | null }>(rows: T[]) =>
    version === null ? [] : rows.filter((row) => row.source_version_id === version.id)

  const produced =
    career === null
      ? null
      : {
          experiences: fromThisVersion(career.experiences),
          education: fromThisVersion(career.education),
          projects: fromThisVersion(career.projects),
          certifications: fromThisVersion(career.certifications),
        }
  const producedCount =
    produced === null
      ? 0
      : produced.experiences.length +
        produced.education.length +
        produced.projects.length +
        produced.certifications.length

  return (
    <div className="space-y-6">
      {/*
        A plain link back. Deliberately not the `backTo` location-state
        machinery JobDetailPage uses — that exists to restore filters and a page
        number, and the resume list has neither.
      */}
      <Link to="/resume" className="text-sm font-medium text-indigo-600 hover:underline">
        ← Back to resumes
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        {/*
          `min-w-48`, not `min-w-0`. With `flex-1` the basis is 0%, and `min-w-0`
          removes the automatic minimum — so the hypothetical width is zero, the
          line can never overflow and the `flex-wrap` above is dead code. The
          heading was therefore squeezed into whatever the `shrink-0` buttons
          left it: about 52px at a 320px viewport. A real floor makes the row
          wrap instead.
        */}
        <div className="min-w-48 flex-1">
          {isRenaming ? (
            /*
              A real form, not ConfirmDialog. That primitive is for actions that
              cannot be undone, its children render outside any form so
              Enter-to-submit would need hand-wiring, and its Escape already
              means cancel. A form gives Enter-to-save for free — the same shape
              CareerSection already uses for its inline edits.
            */
            <form onSubmit={(event) => void saveRename(event)} className="space-y-3" noValidate>
              <Input
                label="Resume name"
                value={draft}
                maxLength={200}
                // Mounted focused with the text selected: the existing name is
                // a raw filename, which people almost always want to replace
                // rather than append to.
                autoFocus
                onFocus={(event) => event.currentTarget.select()}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== 'Escape' || busy !== null) return
                  event.preventDefault()
                  closeRename()
                }}
                {...(actionError !== null ? { error: actionError } : {})}
              />
              <div className="flex items-center gap-3">
                <Button
                  type="submit"
                  size="sm"
                  isLoading={busy === 'rename'}
                  disabled={draft.trim() === ''}
                >
                  Save
                </Button>
                <Button variant="ghost" size="sm" disabled={busy !== null} onClick={closeRename}>
                  Cancel
                </Button>
              </div>
            </form>
          ) : (
            <>
              {/*
                `break-words` because a resume title is a raw filename, so it is
                routinely one unbreakable token: `Parshuram_Bardawal_Resume_2026.pdf`
                rendered as a one-word-per-line tower in a narrow column.
              */}
              <h1 className="text-2xl font-bold tracking-tight break-words text-slate-900">
                {detail.title}
              </h1>
              <p className="mt-1 text-sm text-slate-600">
                Added {formatDateTime(detail.created_at)}
                {version?.processed_at != null && ` · Read ${formatDateTime(version.processed_at)}`}
              </p>
            </>
          )}
          {/* Both changes are otherwise silent to a screen reader. */}
          <p role="status" className="sr-only">
            {announcement}
          </p>
        </div>

        {!isRenaming && (
          <div className="flex shrink-0 items-center gap-2">
            {detail.is_primary ? (
              /*
                A statement, not a disabled button. A disabled control promises
                that something could enable it, and nothing on this page can —
                the only way out is promoting a different resume from its own
                page. The swap is also the feedback, at the spot just clicked.
              */
              <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
                Primary
              </span>
            ) : (
              <Button
                variant="secondary"
                size="sm"
                isLoading={busy === 'primary'}
                disabled={busy !== null}
                onClick={() => void makePrimary()}
              >
                Make primary
              </Button>
            )}
            {/*
              A raw button rather than <Button>: it needs a ref for focus
              return, and Button takes none under strict mode. Same reason
              JobsPage's filters trigger is a raw button.
            */}
            <button
              type="button"
              ref={renameButton}
              disabled={busy !== null}
              onClick={() => {
                setDraft(detail.title)
                setActionError(null)
                setIsRenaming(true)
              }}
              className={buttonClass({ variant: 'ghost', size: 'sm' })}
            >
              Rename
            </button>
          </div>
        )}
      </div>

      {/* The rename form shows its own error under the field. */}
      {actionError !== null && !isRenaming && <Alert tone="error">{actionError}</Alert>}

      {!detail.is_primary && detail.current_version_id === null && (
        <p className="text-sm text-slate-500">
          We couldn&apos;t read this document, so making it primary would leave you with no
          suggested skills until it parses.
        </p>
      )}

      {version === null ? (
        <Alert tone="info">This resume has no uploaded file.</Alert>
      ) : (
        <>
          {hasFailed && (
            <Alert tone="error" title="We couldn't read this document">
              {version.processing_error ?? 'No reason was recorded.'}
            </Alert>
          )}
          {isProcessing && (
            <Alert tone="info">
              We&apos;re still reading this document. Refresh in a moment to see what it found.
            </Alert>
          )}

          <ResumeFilePreview
            versionId={version.id}
            mimeType={version.mime_type}
            filename={version.original_filename}
            fileSizeBytes={version.file_size_bytes}
          />

          <Section
            title="What we read"
            hint={
              pages != null || characters != null
                ? `${pages ?? '?'} page${pages === 1 ? '' : 's'}, ${
                    characters?.toLocaleString() ?? '?'
                  } characters of text.`
                : undefined
            }
          >
            {sections.length === 0 ? (
              <p className="text-sm text-slate-500">
                No headings were found in this document. That usually means the sections below were
                harder to identify.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {sections.map((section, index) => (
                  <Chip key={`${section.type}-${index}`}>{section.heading ?? section.type}</Chip>
                ))}
              </div>
            )}
          </Section>

          <Section
            title={`Skills this document mentioned${skills.length > 0 ? ` (${skills.length})` : ''}`}
            hint="What this read found. Your profile's skill list is managed on the resume page."
          >
            {skills.length === 0 ? (
              <p className="text-sm text-slate-500">No skills were found in this document.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {skills.map((skill) => (
                  <Chip key={skill.name} muted={!skill.accepted}>
                    {skill.name} · {Math.round(skill.confidence * 100)}%
                    {!skill.accepted && ' · needs review'}
                  </Chip>
                ))}
              </div>
            )}
          </Section>

          <Section
            title="What this added to your profile"
            hint="Edit any of these on your profile."
          >
            {careerFailed ? (
              <p className="text-sm text-slate-500">
                Couldn&apos;t load what this resume added. The rest of this page is unaffected.
              </p>
            ) : produced === null ? (
              <Spinner className="size-5 text-slate-400" label="Loading" />
            ) : producedCount === 0 ? (
              <p className="text-sm text-slate-500">
                Nothing on your profile came from this document.
              </p>
            ) : (
              <div className="space-y-4">
                {produced.experiences.length > 0 && (
                  <div>
                    <h3 className="text-sm font-medium text-slate-900">Work experience</h3>
                    <ul className="mt-1 space-y-1">
                      {produced.experiences.map((row) => (
                        <li key={row.id} className="text-sm text-slate-600">
                          {row.title}
                          {row.company_name !== null && ` · ${row.company_name}`}
                          {formatSpan(row) !== null && ` · ${formatSpan(row)}`}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {produced.education.length > 0 && (
                  <div>
                    <h3 className="text-sm font-medium text-slate-900">Education</h3>
                    <ul className="mt-1 space-y-1">
                      {produced.education.map((row) => (
                        <li key={row.id} className="text-sm text-slate-600">
                          {row.institution}
                          {formatSpan(row) !== null && ` · ${formatSpan(row)}`}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {produced.projects.length > 0 && (
                  <div>
                    <h3 className="text-sm font-medium text-slate-900">Projects</h3>
                    <ul className="mt-1 space-y-1">
                      {produced.projects.map((row) => (
                        <li key={row.id} className="text-sm text-slate-600">
                          {row.name}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {produced.certifications.length > 0 && (
                  <div>
                    <h3 className="text-sm font-medium text-slate-900">Certifications</h3>
                    <ul className="mt-1 space-y-1">
                      {produced.certifications.map((row) => (
                        <li key={row.id} className="text-sm text-slate-600">
                          {row.name}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </Section>

          {detail.versions.length > 1 && (
            <Section
              title="Earlier versions"
              hint="An older version was read by an older parser, so what it found may since have been replaced."
            >
              <ul className="space-y-2">
                {detail.versions.map((entry) => (
                  <li key={entry.id} className="flex flex-wrap items-center gap-2 text-sm">
                    {entry.id === version.id ? (
                      <span className="font-medium text-slate-900">
                        v{entry.version_number} (showing)
                      </span>
                    ) : (
                      <Link
                        to={`/resume/${detail.id}?v=${entry.id}`}
                        className="font-medium text-indigo-600 hover:underline"
                      >
                        v{entry.version_number}
                      </Link>
                    )}
                    <span className="text-slate-500">
                      {entry.original_filename} · {formatFileSize(entry.file_size_bytes)} ·{' '}
                      {formatDateTime(entry.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {/*
            Collapsed and height-capped. A 30,000-character resume would
            otherwise own the page, but hiding it entirely takes away the one
            thing that explains a bad parse.
          */}
          <details className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
            <summary className="cursor-pointer text-sm font-medium text-indigo-600 hover:underline">
              Show the text we read
            </summary>
            {version.raw_text === null || version.raw_text === '' ? (
              <p className="mt-3 text-sm text-slate-500">
                No text could be read from this document.
              </p>
            ) : (
              <pre className="mt-3 max-h-96 overflow-auto rounded-md bg-slate-50 p-3 text-xs whitespace-pre-wrap text-slate-700">
                {version.raw_text}
              </pre>
            )}
          </details>
        </>
      )}
    </div>
  )
}
