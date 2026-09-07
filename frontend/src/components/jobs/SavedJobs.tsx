import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { JobSaveControls, UnsaveConfirmation } from '@/components/JobSaveControls'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { useJobApplication } from '@/hooks/useJobApplication'
import { applicationService } from '@/services/applicationService'
import type { ApplicationListItem, ApplicationRead } from '@/types/application'
import { formatSalary } from '@/types/job'
import { formatDateTime } from '@/utils/datetime'

/**
 * Jobs you saved, and jobs you marked applied.
 *
 * One component rendering two sections from one request, not two independent
 * ones. The lists are a single question and entries move between them —
 * unticking "I have applied" belongs in Saved from that moment — so two
 * components each owning their own load would need either two refetches or
 * shared state, and would leave a window where a row is in both lists or
 * neither. Same reasoning as the single `GET /profile/career`.
 *
 * The endpoint takes a `?status=` filter; this deliberately does not use it.
 */

function Row({
  item,
  onChange,
}: {
  item: ApplicationListItem
  onChange: (next: ApplicationRead | null) => void
}) {
  const state = useJobApplication(item.job_id, item, onChange)
  const salary = formatSalary(item.job)
  const when =
    item.status === 'APPLIED' && item.applied_at !== null
      ? `Applied ${formatDateTime(item.applied_at)}`
      : `Saved ${formatDateTime(item.created_at)}`

  return (
    <li className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 py-4 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1">
        <Link
          to={`/jobs/${item.job_id}`}
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
          {when}
          {salary !== null && <span> · {salary}</span>}
        </p>
      </div>
      {/* The same controls as the card, so someone pruning their list here does
          not have to open every job to do it. */}
      <JobSaveControls state={state} jobTitle={item.job.title} variant="icon" />
      <UnsaveConfirmation state={state} />
    </li>
  )
}

function Section({
  title,
  description,
  items,
  empty,
  onChange,
}: {
  title: string
  description: string
  items: ApplicationListItem[]
  empty: React.ReactNode
  onChange: (jobId: string, next: ApplicationRead | null) => void
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6">
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      <p className="mt-1 text-sm text-slate-600">{description}</p>
      {items.length === 0 ? (
        <div className="mt-4 text-sm text-slate-500">{empty}</div>
      ) : (
        <ul className="mt-4 divide-y divide-slate-200">
          {items.map((item) => (
            <Row key={item.id} item={item} onChange={(next) => onChange(item.job_id, next)} />
          ))}
        </ul>
      )}
    </section>
  )
}

export function SavedJobs() {
  const [items, setItems] = useState<ApplicationListItem[]>([])
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading')

  const load = useCallback(() => {
    setLoadState('loading')
    applicationService.list().then(
      (result) => {
        setItems(result.items)
        setLoadState('ready')
      },
      // An error state rather than an empty one: telling someone they have
      // saved nothing when the request merely failed is a lie they may act on.
      () => setLoadState('error'),
    )
  }, [])

  useEffect(load, [load])

  function apply(jobId: string, next: ApplicationRead | null) {
    setItems((previous) =>
      next === null
        ? previous.filter((row) => row.job_id !== jobId)
        : // Moves the row between the two sections without a refetch, because
          // both are derived from this one list.
          previous.map((row) => (row.job_id === jobId ? { ...row, ...next } : row)),
    )
  }

  if (loadState === 'loading') {
    return (
      <div className="flex justify-center py-10">
        <Spinner className="size-6 text-indigo-600" label="Loading your saved jobs" />
      </div>
    )
  }

  if (loadState === 'error') {
    return (
      <div className="space-y-3">
        <Alert tone="error" title="We couldn't load your saved jobs">
          Please try again.
        </Alert>
        <Button variant="secondary" size="sm" onClick={load}>
          Try again
        </Button>
      </div>
    )
  }

  // Disjoint on purpose. An applied job in both lists would make "Saved" a
  // to-do list that never empties; that it is still saved stays visible on the
  // job itself, where the bookmark is filled.
  const saved = items.filter((item) => item.status === 'SAVED')
  const applied = items.filter((item) => item.status === 'APPLIED')

  return (
    <div className="space-y-6">
      <Section
        // "Saved", not "Saved jobs": the page above already carries that as
        // its h1, and repeating it puts two identical headings in a row.
        title="Saved"
        description="Jobs you bookmarked to come back to."
        items={saved}
        onChange={apply}
        empty={
          <>
            Nothing saved yet. Bookmark a job while{' '}
            <Link to="/jobs" className="text-indigo-600 hover:underline">
              browsing
            </Link>{' '}
            and it lands here.
          </>
        }
      />
      <Section
        title="Applications"
        description="Jobs you told us you applied to. Nothing here is inferred — you marked each one."
        items={applied}
        onChange={apply}
        empty={<>Nothing marked applied yet. Tick &ldquo;I have applied&rdquo; on a job.</>}
      />
    </div>
  )
}
