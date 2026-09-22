import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ForgetAppliedConfirmation, JobSaveControls } from '@/components/JobSaveControls'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { DropdownMenu, menuItemClass } from '@/components/ui/DropdownMenu'
import { Spinner } from '@/components/ui/Spinner'
import { useJobApplication } from '@/hooks/useJobApplication'
import { useJobBackState } from '@/hooks/useJobBackState'
import { ApiError } from '@/services/apiClient'
import { applicationService } from '@/services/applicationService'
import {
  FUNNEL,
  STATUS_FILL,
  STATUS_LABEL,
  STATUS_TONE,
  TERMINAL,
  type ApplicationListItem,
  type ApplicationRead,
  type ApplicationStatus,
} from '@/types/application'
import { cn } from '@/utils/cn'
import { formatDateTime, formatPostedAge } from '@/utils/datetime'
import { cardClass, PILL_SHAPE } from '@/components/ui/cardStyles'

/**
 * Every application, grouped by the stage it is in (US-7.1).
 *
 * A grouped list rather than a drag-and-drop board. Dragging needs a pointer,
 * and this has to work on the phone somebody checks between interviews — a
 * menu is operable by touch, by keyboard and by a screen reader without any of
 * the three being a special case.
 *
 * ## The allowed moves come from the server, and are not duplicated here
 *
 * Every stage is offered. A move the funnel disallows comes back as a 409
 * carrying `details.allowed`, and that is what gets shown. The alternative —
 * filtering the options client-side — means a second copy of the transition
 * rules that drifts from the first, and the drift is invisible until somebody
 * cannot make a move the backend would have accepted.
 *
 * ## Two kinds of change, two update strategies, on purpose
 *
 * A **stage move** refetches: the transition can change more than the row that
 * moved, because returning to SAVED clears `applied_at` server-side, and a
 * refetch cannot disagree with the server.
 *
 * A **bookmark toggle** patches locally, through `useJobApplication`, which is
 * optimistic by design — a spinner on a bookmark for a 200ms round trip reads
 * as broken. These are not inconsistent: one changes a field the server
 * derives, the other flips a bit the client already knows the value of.
 *
 * ## This absorbed the Saved jobs page
 *
 * `/saved-jobs` was a second view of these same rows with different controls,
 * and two views of one list can disagree. Its bookmark and remove controls moved
 * onto these rows rather than being reimplemented — `useJobApplication` owns the
 * confirm-before-discarding flow that US-7.0 AC3 requires, and a fresh
 * implementation would not have had it.
 */

function StatusPill({ status, className }: { status: ApplicationStatus; className?: string }) {
  return (
    <span
      className={cn(PILL_SHAPE, STATUS_TONE[status], className)}
    >
      {STATUS_LABEL[status]}
    </span>
  )
}

/**
 * The whole funnel in one card, before any list.
 *
 * Bars rather than bare counts because the shape is the point — where people
 * fall out is visible at a glance and a column of numbers does not show it.
 * Widths are relative to the busiest stage, not to the total: with six
 * applications spread one per stage, every share of the total rounds to a
 * stripe too thin to see.
 */
function FunnelSummary({ items }: { items: ApplicationListItem[] }) {
  const counts = FUNNEL.map((status) => ({
    status,
    count: items.filter((item) => item.status === status).length,
  }))
  const busiest = Math.max(...counts.map((entry) => entry.count), 1)
  const stopped = items.filter((item) => TERMINAL.includes(item.status)).length

  return (
    <section
      aria-labelledby="funnel-heading"
      className={cardClass()}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="funnel-heading" className="text-base font-semibold text-slate-900">
          Your funnel
        </h2>
        <p className="text-sm text-slate-500">
          <span className="tabular-nums">{items.length - stopped}</span> active
          {stopped > 0 && (
            <>
              {' · '}
              <span className="tabular-nums">{stopped}</span> closed
            </>
          )}
        </p>
      </div>

      <ol className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-5">
        {counts.map(({ status, count }) => (
          <li key={status}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-xs font-medium text-slate-600">
                {STATUS_LABEL[status]}
              </span>
              <span
                className={cn(
                  'text-sm tabular-nums',
                  count === 0 ? 'text-slate-300' : 'font-semibold text-slate-900',
                )}
              >
                {count}
              </span>
            </div>
            <div
              className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100"
              role="meter"
              aria-valuenow={count}
              aria-valuemin={0}
              aria-valuemax={busiest}
              aria-label={`${STATUS_LABEL[status]}: ${count}`}
            >
              <div
                className={cn('h-full rounded-full', STATUS_FILL[status])}
                style={{ width: `${(count / busiest) * 100}%` }}
              />
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

function Row({
  item,
  onMoved,
  onRefused,
  onLocalChange,
}: {
  item: ApplicationListItem
  onMoved: () => void
  onRefused: (message: string) => void
  onLocalChange: (jobId: string, next: ApplicationRead | null) => void
}) {
  const [busy, setBusy] = useState(false)
  const backState = useJobBackState()
  const saveState = useJobApplication(item.job_id, item, (next) =>
    onLocalChange(item.job_id, next),
  )

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

  const age = item.applied_at ?? item.created_at

  return (
    <li className="flex items-start justify-between gap-3 py-3 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1">
        <Link
          to={`/jobs/${item.job_id}`}
          state={backState}
          className="text-sm font-medium text-slate-900 hover:text-indigo-700 hover:underline"
        >
          {item.job.title}
        </Link>
        <p className="truncate text-sm text-slate-600">
          {item.job.company?.name ?? 'Company not stated'}
          {item.job.location !== null && (
            <span className="text-slate-400"> · {item.job.location}</span>
          )}
        </p>
        <p className="mt-0.5 text-xs text-slate-500">
          {item.applied_at === null
            ? `Saved ${formatDateTime(item.created_at)}`
            : `Applied ${formatDateTime(item.applied_at)}`}
          {/* How long it has sat is the question this page exists to answer,
              and an absolute date alone does not answer it. */}
          <span className="text-slate-400"> · {formatPostedAge(age)}</span>
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-1">
        <JobSaveControls state={saveState} jobTitle={item.job.title} variant="icon" />

        <DropdownMenu
          align="right"
          label={`Move ${item.job.title} to another stage`}
          triggerClassName={cn(
            'rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700',
            'hover:bg-slate-50 disabled:opacity-50',
          )}
          trigger={<span>{busy ? 'Moving…' : 'Move'}</span>}
        >
          {[...FUNNEL, ...TERMINAL].map((status) => {
            const current = status === item.status
            return (
              <button
                key={status}
                role="menuitem"
                tabIndex={-1}
                type="button"
                disabled={current}
                onClick={() => void move(status)}
                className={cn(
                  menuItemClass,
                  'flex items-center justify-between gap-3',
                  current && 'cursor-default text-slate-400',
                )}
              >
                {STATUS_LABEL[status]}
                {current && <span className="text-xs text-slate-400">Current</span>}
              </button>
            )
          })}
        </DropdownMenu>
      </div>

      <ForgetAppliedConfirmation state={saveState} />
    </li>
  )
}

function StageCard({
  status,
  rows,
  onMoved,
  onRefused,
  onLocalChange,
}: {
  status: ApplicationStatus
  rows: ApplicationListItem[]
  onMoved: () => void
  onRefused: (message: string) => void
  onLocalChange: (jobId: string, next: ApplicationRead | null) => void
}) {
  return (
    <section
      aria-labelledby={`stage-${status}`}
      className={cardClass()}
    >
      {/*
        The stage name lives *inside* the heading, not beside it. Putting the
        pill outside made the section's accessible name "1 job" — a screen
        reader announced every card identically and never said which stage it
        was, which is the entire information this page carries.
      */}
      <h2 id={`stage-${status}`} className="flex items-center gap-2">
        <StatusPill status={status} />
        <span className="text-sm text-slate-500">
          <span className="tabular-nums">{rows.length}</span>
          {rows.length === 1 ? ' job' : ' jobs'}
        </span>
      </h2>

      <ul className="mt-3 divide-y divide-slate-100">
        {rows.map((item) => (
          <Row
            key={item.id}
            item={item}
            onMoved={onMoved}
            onRefused={onRefused}
            onLocalChange={onLocalChange}
          />
        ))}
      </ul>
    </section>
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

  // A bookmark toggle, unlike a stage move: `useJobApplication` is optimistic
  // and has already decided, so this only keeps the rendered list in step.
  const onLocalChange = useCallback((jobId: string, next: ApplicationRead | null) => {
    setItems((previous) => {
      if (previous === null) return previous
      return next === null
        ? previous.filter((row) => row.job_id !== jobId)
        : previous.map((row) => (row.job_id === jobId ? { ...row, ...next } : row))
    })
  }, [])

  if (error !== null) {
    return (
      <div className="space-y-3">
        <Alert tone="error" title="We couldn't load your applications">
          Please try again.
        </Alert>
        <Button variant="secondary" size="sm" onClick={() => void load()}>
          Try again
        </Button>
      </div>
    )
  }

  if (items === null) {
    return (
      <div className="flex justify-center py-10">
        <Spinner className="size-6 text-indigo-600" label="Loading your applications" />
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center">
        <p className="text-sm text-slate-600">
          Nothing here yet. Save a job or mark one applied and it will show up, with every stage it
          passes through.
        </p>
        {/* A way in, not just an explanation. Carried over from the Saved jobs
            page this screen replaced, where it was the one thing an empty state
            has to offer. */}
        <Link
          to="/jobs"
          className="mt-3 inline-block text-sm font-medium text-indigo-700 hover:underline"
        >
          Browse jobs
        </Link>
      </div>
    )
  }

  // Terminal stages last, and only when they hold something: a permanently
  // visible empty "Rejected" card is a discouraging thing to render on
  // somebody's job hunt for no information.
  const stages = [...FUNNEL, ...TERMINAL]

  return (
    <div className="space-y-4">
      {refusal !== null && <Alert tone="error">{refusal}</Alert>}

      <FunnelSummary items={items} />

      {stages.map((status) => {
        const rows = items.filter((item) => item.status === status)
        if (rows.length === 0) return null
        return (
          <StageCard
            key={status}
            status={status}
            rows={rows}
            onMoved={onMoved}
            onRefused={setRefusal}
            onLocalChange={onLocalChange}
          />
        )
      })}
    </div>
  )
}
