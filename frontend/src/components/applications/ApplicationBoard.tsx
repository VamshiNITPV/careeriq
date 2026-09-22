import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Spinner } from '@/components/ui/Spinner'
import { useJobBackState } from '@/hooks/useJobBackState'
import { ApiError } from '@/services/apiClient'
import { applicationService } from '@/services/applicationService'
import {
  FUNNEL,
  STATUS_LABEL,
  STATUS_TONE,
  TERMINAL,
  type ApplicationListItem,
  type ApplicationStatus,
} from '@/types/application'
import { formatDateTime } from '@/utils/datetime'

/**
 * Every application, grouped by the stage it is in (US-7.1).
 *
 * A grouped list rather than a drag-and-drop board. Dragging needs a pointer,
 * and this has to work on the phone somebody checks between interviews — a
 * select is operable by touch, by keyboard and by a screen reader without any
 * of the three being a special case.
 *
 * ## The allowed moves come from the server, and are not duplicated here
 *
 * Every stage is offered. A move the funnel disallows comes back as a 409
 * carrying `details.allowed`, and that is what gets shown. The alternative —
 * filtering the options client-side — means a second copy of the transition
 * rules that drifts from the first, and the drift is invisible until somebody
 * cannot make a move the backend would have accepted.
 *
 * ## Why the whole list reloads after a move
 *
 * A transition can change more than the row that moved: returning to SAVED
 * clears `applied_at` server-side. Patching the row locally from the response
 * is possible, but a refetch is one request on a list bounded by how many jobs
 * one person applies to, and it cannot disagree with the server.
 */

function StatusPill({ status }: { status: ApplicationStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_TONE[status]}`}
    >
      {STATUS_LABEL[status]}
    </span>
  )
}

function Row({
  item,
  onMoved,
  onRefused,
}: {
  item: ApplicationListItem
  onMoved: () => void
  onRefused: (message: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const backState = useJobBackState()

  async function move(next: ApplicationStatus) {
    if (next === item.status) return
    setBusy(true)
    try {
      await applicationService.changeStatus(item.id, next)
      onMoved()
    } catch (error) {
      // The server's own answer, including which moves it would accept. A
      // generic "something went wrong" would hide the one useful fact.
      if (error instanceof ApiError) {
        const allowed = error.details.allowed
        const where = Array.isArray(allowed)
          ? ` You can move it to: ${allowed
              .map((s) => STATUS_LABEL[s as ApplicationStatus] ?? String(s))
              .join(', ')}.`
          : ''
        onRefused(`${error.message}${where}`)
      } else {
        onRefused('That change could not be saved.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 py-4 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1">
        <Link
          to={`/jobs/${item.job_id}`}
          state={backState}
          className="text-sm font-medium text-indigo-700 hover:underline"
        >
          {item.job.title}
        </Link>
        <p className="text-sm text-slate-600">
          {item.job.company?.name ?? 'Company not stated'}
          {item.job.location !== null && (
            <span className="text-slate-400"> · {item.job.location}</span>
          )}
        </p>
        <p className="mt-0.5 text-xs text-slate-500">
          {item.applied_at === null
            ? `Saved ${formatDateTime(item.created_at)}`
            : `Applied ${formatDateTime(item.applied_at)}`}
        </p>
      </div>

      <label className="flex items-center gap-2 text-xs text-slate-600">
        <span className="sr-only">Move {item.job.title} to</span>
        <select
          value={item.status}
          disabled={busy}
          onChange={(event) => void move(event.target.value as ApplicationStatus)}
          className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 disabled:opacity-50"
        >
          {[...FUNNEL, ...TERMINAL].map((status) => (
            <option key={status} value={status}>
              {STATUS_LABEL[status]}
            </option>
          ))}
        </select>
      </label>
    </li>
  )
}

export function ApplicationBoard() {
  const [items, setItems] = useState<ApplicationListItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refusal, setRefusal] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const response = await applicationService.list()
      setItems(response.items)
      setError(null)
    } catch {
      setError('Your applications could not be loaded.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const onMoved = useCallback(() => {
    setRefusal(null)
    void load()
  }, [load])

  if (error !== null) return <Alert tone="error">{error}</Alert>
  if (items === null) return <Spinner label="Loading your applications" />

  if (items.length === 0) {
    return (
      <p className="text-sm text-slate-600">
        Nothing here yet. Save a job or mark one applied and it will show up, with every stage it
        passes through.
      </p>
    )
  }

  // Terminal stages last, and only when they hold something: a permanently
  // visible empty "Rejected" heading is a discouraging thing to render on
  // somebody's job hunt for no information.
  const stages = [...FUNNEL, ...TERMINAL]

  return (
    <div className="space-y-6">
      {refusal !== null && <Alert tone="error">{refusal}</Alert>}

      <ol className="flex flex-wrap gap-2" aria-label="Funnel summary">
        {FUNNEL.map((status) => (
          <li key={status} className="flex items-center gap-1.5">
            <StatusPill status={status} />
            <span className="text-sm tabular-nums text-slate-700">
              {items.filter((item) => item.status === status).length}
            </span>
          </li>
        ))}
      </ol>

      {stages.map((status) => {
        const rows = items.filter((item) => item.status === status)
        if (rows.length === 0) return null
        return (
          <section key={status} aria-labelledby={`stage-${status}`}>
            <h2
              id={`stage-${status}`}
              className="text-sm font-semibold tracking-tight text-slate-900"
            >
              {STATUS_LABEL[status]}{' '}
              <span className="font-normal text-slate-500">({rows.length})</span>
            </h2>
            <ul className="mt-1 divide-y divide-slate-100">
              {rows.map((item) => (
                <Row key={item.id} item={item} onMoved={onMoved} onRefused={setRefusal} />
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
