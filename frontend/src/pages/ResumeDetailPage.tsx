import { useCallback, useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ResumeFilePreview } from '@/components/resume/ResumeFilePreview'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { ApiError } from '@/services/apiClient'
import { careerService } from '@/services/careerService'
import { resumeService } from '@/services/resumeService'
import { formatSpan, type CareerSummary } from '@/types/career'
import {
  formatFileSize,
  IN_FLIGHT,
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

      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">{detail.title}</h1>
        <p className="mt-1 text-sm text-slate-600">
          Added {formatDateTime(detail.created_at)}
          {detail.is_primary && ' · Primary resume'}
          {version?.processed_at != null && ` · Read ${formatDateTime(version.processed_at)}`}
        </p>
      </div>

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
