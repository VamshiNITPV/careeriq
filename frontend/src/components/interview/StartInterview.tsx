import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Combobox } from '@/components/ui/Combobox'
import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'
import type { ComboboxOption } from '@/components/ui/comboboxCore'
import { applicationService } from '@/services/applicationService'
import { interviewService } from '@/services/interviewService'
import { jobService } from '@/services/jobService'
import type { ApplicationListItem, ApplicationStatus } from '@/types/application'
import { STATUS_LABEL } from '@/types/application'
import { MIN_DESCRIPTION_CHARS } from '@/types/job'
import { externalLink } from '@/utils/externalUrl'

/**
 * Which applications can be rehearsed against.
 *
 * Applied and everything past it. Not SAVED — a bookmark is a maybe, and a list
 * of maybes buries the three interviews you actually have. Not REJECTED or
 * WITHDRAWN either: those are reachable from SAVED without ever applying, so
 * they are not reliably "a job you went for", and rehearsing for one is not
 * what anybody opens this page to do.
 */
const REHEARSABLE: readonly ApplicationStatus[] = [
  'APPLIED',
  'ASSESSMENT',
  'INTERVIEW',
  'OFFER',
]

type Mode = 'role' | 'posting' | 'applied'

const MODES: readonly { value: Mode; label: string; hint: string }[] = [
  {
    value: 'role',
    label: 'Just a role',
    hint: 'Questions come from what postings for that title generally ask for.',
  },
  {
    value: 'posting',
    label: 'Paste a posting',
    hint: 'Questions come from what that posting itself asks for. The sharpest of the three.',
  },
  {
    value: 'applied',
    label: 'A job you applied to',
    hint: 'Same as pasting one, without the pasting.',
  },
]

function message(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

export function StartInterview() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>('role')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [role, setRole] = useState('')
  const [description, setDescription] = useState('')
  const [link, setLink] = useState('')
  const [title, setTitle] = useState('')
  const [company, setCompany] = useState('')

  const [applications, setApplications] = useState<ApplicationListItem[] | null>(null)
  const [applicationsFailed, setApplicationsFailed] = useState(false)
  const [chosenJob, setChosenJob] = useState('')

  /*
   * Fetched on the first switch into the picker, not on mount.
   *
   * Role is the default mode and the common one; making every visit to this page
   * pay for a list most people will not open is a cost with no return.
   */
  useEffect(() => {
    if (mode !== 'applied' || applications !== null || applicationsFailed) return
    applicationService.list().then(
      (response) => setApplications(response.items),
      () => setApplicationsFailed(true),
    )
  }, [mode, applications, applicationsFailed])

  const options: ComboboxOption[] = (applications ?? [])
    .filter((item) => REHEARSABLE.includes(item.status))
    .map((item) => ({
      value: item.job_id,
      label: item.job.title,
      // Shown *and* searched, so typing a company name finds the job.
      description: [item.job.company?.name, item.job.location, STATUS_LABEL[item.status]]
        .filter(Boolean)
        .join(' · '),
    }))

  const chosen = options.find((option) => option.value === chosenJob)

  const start = useCallback(
    async (body: { target_role: string; target_job_id?: string }) => {
      const started = await interviewService.start(body)
      navigate(`/interviews/${started.interview_id}`)
    },
    [navigate],
  )

  function submit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)

    if (mode === 'role') {
      const target = role.trim()
      if (target.length < 2) {
        setError('Tell us the role you are preparing for.')
        return
      }
      setBusy(true)
      // Exactly this body and nothing else. A `target_job_id: undefined` would
      // serialise away, but the shape of the call is what the existing tests
      // pin, and role-only genuinely has no job.
      start({ target_role: target }).catch((cause: unknown) => {
        setBusy(false)
        setError(message(cause, "We couldn't start that interview."))
      })
      return
    }

    if (mode === 'applied') {
      if (!chosen) {
        setError('Pick a job first.')
        return
      }
      setBusy(true)
      start({ target_role: chosen.label, target_job_id: chosen.value }).catch(
        (cause: unknown) => {
          setBusy(false)
          setError(message(cause, "We couldn't start that interview."))
        },
      )
      return
    }

    const text = description.trim()
    if (text.length < MIN_DESCRIPTION_CHARS) {
      setError(
        `Paste a bit more of the posting — we need at least ${MIN_DESCRIPTION_CHARS} characters to read the requirements out of it.`,
      )
      return
    }
    const typedLink = link.trim()
    if (typedLink && externalLink(typedLink, { assumeHttps: true }) === null) {
      // Refused rather than dropped: somebody who typed a link wrong wants to
      // know, and discarding it leaves the posting looking like one they never
      // had a link for.
      setError("That link doesn't look right. Fix it, or clear the box.")
      return
    }

    setBusy(true)
    /*
     * Two calls, and the order matters if the second fails.
     *
     * The job is a legitimate corpus row either way — it belongs in the jobs
     * list regardless of whether an interview got started against it — and a
     * retried paste dedups to the same row by content hash. So the orphan is
     * benign, and the error says where the work went rather than implying it
     * was lost.
     */
    jobService
      .submit({
        description: text,
        ...(title.trim() ? { title: title.trim() } : {}),
        ...(company.trim() ? { company: company.trim() } : {}),
        ...(typedLink ? { source_url: typedLink } : {}),
      })
      .then(
        (added) =>
          start({
            target_role: title.trim() || added.job.title,
            target_job_id: added.job.id,
          }).catch((cause: unknown) => {
            setBusy(false)
            setError(
              `${message(cause, "We couldn't start the interview.")} The posting was saved — you can find it in Jobs.`,
            )
          }),
        (cause: unknown) => {
          setBusy(false)
          setError(message(cause, "We couldn't read that as a job posting."))
        },
      )
  }

  const active = MODES.find((option) => option.value === mode)

  return (
    <form onSubmit={submit} className="space-y-4">
      <fieldset>
        <legend className="text-sm font-medium text-slate-900">
          How should we build the questions?
        </legend>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
          {MODES.map((option) => (
            <label key={option.value} className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="radio"
                name="interview-mode"
                value={option.value}
                checked={mode === option.value}
                onChange={() => {
                  setMode(option.value)
                  setError(null)
                }}
                disabled={busy}
                className="size-4 border-slate-300 text-indigo-600 focus:ring-indigo-500"
              />
              {option.label}
            </label>
          ))}
        </div>
        {active && <p className="mt-1.5 text-xs text-slate-500">{active.hint}</p>}
      </fieldset>

      {/* Rendered conditionally, never hidden with CSS: a hidden field is still
          in the accessibility tree and still queryable, so an assertion that a
          field is absent would pass on a bug. */}
      {mode === 'role' && (
        <Input
          label="Role you are preparing for"
          value={role}
          onChange={(event) => setRole(event.target.value)}
          placeholder="AI Engineer"
          // Free text rather than a picker: somebody can rehearse for a role
          // this corpus has never carried a posting for, and making them choose
          // from a list would fail exactly the person preparing for something
          // they have not found yet.
          maxLength={200}
          disabled={busy}
        />
      )}

      {mode === 'posting' && (
        <div className="space-y-3">
          <Textarea
            label="The posting"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={8}
            disabled={busy}
            hint="Open the job and paste the whole thing — requirements and responsibilities especially. We read the skills out of it."
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label="Link to the posting (optional)"
              value={link}
              onChange={(event) => setLink(event.target.value)}
              placeholder="https://jobs.example.com/backend-engineer"
              disabled={busy}
              hint="Kept for reference. We never open it."
            />
            <Input
              label="Role (optional)"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Read from the posting if you leave this"
              maxLength={200}
              disabled={busy}
            />
          </div>
          <Input
            label="Company (optional)"
            value={company}
            onChange={(event) => setCompany(event.target.value)}
            maxLength={200}
            disabled={busy}
          />
        </div>
      )}

      {mode === 'applied' && (
        <>
          {applicationsFailed ? (
            <Alert tone="error">
              We couldn&apos;t load your applications. Try one of the other two ways above.
            </Alert>
          ) : applications === null ? (
            <p className="text-sm text-slate-500">Loading your applications…</p>
          ) : options.length === 0 ? (
            <Alert tone="info">
              Nothing to pick yet — jobs show up here once you mark them applied.{' '}
              <Link to="/applications" className="font-medium underline">
                Your applications
              </Link>
            </Alert>
          ) : (
            <Combobox
              label="Which job?"
              options={options}
              value={chosenJob}
              onChange={setChosenJob}
              placeholder="Search by title or company"
              disabled={busy}
            />
          )}
        </>
      )}

      {error && <Alert tone="error">{error}</Alert>}

      <div className="flex items-center gap-3">
        <Button type="submit" isLoading={busy}>
          Start
        </Button>
        <span className="text-xs text-slate-500">
          Ten questions, and it adapts as you go. You can close the tab and come back.
        </span>
      </div>
    </form>
  )
}
