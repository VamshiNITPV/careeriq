import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'
import { ApiError } from '@/services/apiClient'
import { jobService } from '@/services/jobService'
import { MIN_DESCRIPTION_CHARS } from '@/types/job'

/**
 * Paste a job description (US-3.1).
 *
 * No polling, unlike a resume upload: parsing is synchronous server-side, so
 * the parsed job comes back in the same response and this navigates straight
 * to it.
 */

export function AddJobPage() {
  const navigate = useNavigate()

  const [description, setDescription] = useState('')
  const [title, setTitle] = useState('')
  const [company, setCompany] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<ApiError | string | null>(null)

  const trimmed = description.trim()
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_DESCRIPTION_CHARS

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSaving(true)
    try {
      const result = await jobService.submit({
        description: trimmed,
        ...(title.trim() ? { title: title.trim() } : {}),
        ...(company.trim() ? { company: company.trim() } : {}),
        ...(sourceUrl.trim() ? { source_url: sourceUrl.trim() } : {}),
      })
      // A duplicate returns the job that already existed, so navigating there
      // is right either way. The banner on the detail page explains which
      // happened rather than this page pretending it created something.
      navigate(`/jobs/${result.job.id}`, {
        state: { isDuplicate: result.is_duplicate },
        replace: true,
      })
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : 'Could not add that job. Please check your connection and try again.',
      )
      setIsSaving(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <Link to="/jobs" className="text-sm font-medium text-indigo-600 hover:underline">
          ← Back to jobs
        </Link>
        <h1 className="mt-2 text-2xl font-bold tracking-tight text-slate-900">Add a job</h1>
        <p className="mt-1 text-sm text-slate-600">
          Paste the full posting. We&apos;ll pull out the title, company, location, pay and the
          skills it asks for.
        </p>
      </div>

      {typeof error === 'string' && (
        <Alert tone="error" title="We couldn't add that job">
          {error}
        </Alert>
      )}
      {error instanceof ApiError && (
        <Alert tone="error" title="We couldn't add that job" correlationId={error.correlationId}>
          {error.message}
        </Alert>
      )}

      <form
        onSubmit={(e) => void onSubmit(e)}
        className="space-y-4 rounded-xl border border-slate-200 bg-white p-6"
        noValidate
      >
        <Textarea
          label="Job description"
          required
          rows={16}
          placeholder="Paste the whole posting here, including its requirements section."
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          hint={
            tooShort
              ? undefined
              : 'The requirements section is what tells us which skills are mandatory.'
          }
          // Shown while typing rather than only on submit: the server enforces
          // the same minimum, and finding out after a round trip is worse.
          error={
            tooShort
              ? `A bit more, please — ${trimmed.length} of ${MIN_DESCRIPTION_CHARS} characters.`
              : undefined
          }
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Title"
            hint="Only if we get it wrong"
            placeholder="Read from the posting"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <Input
            label="Company"
            hint="Only if we get it wrong"
            placeholder="Read from the posting"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
          />
        </div>

        <Input
          label="Link to the posting"
          type="url"
          placeholder="https://…"
          value={sourceUrl}
          onChange={(e) => setSourceUrl(e.target.value)}
        />

        <div className="flex items-center gap-3 pt-2">
          <Button type="submit" isLoading={isSaving} disabled={trimmed.length === 0 || tooShort}>
            Add job
          </Button>
          <Link to="/jobs" className="text-sm text-slate-600 hover:text-slate-900">
            Cancel
          </Link>
        </div>
      </form>
    </div>
  )
}
