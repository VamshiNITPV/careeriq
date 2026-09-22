import { useCallback, useEffect, useState } from 'react'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { applicationService } from '@/services/applicationService'
import type { FunnelAnalyticsResponse, FunnelSegment } from '@/types/application'
import { cardClass } from '@/components/ui/cardStyles'

/**
 * How the applications have gone — counts, and rates where there are enough
 * of them to mean anything (US-7.2).
 *
 * ## Deliberately not a chart
 *
 * Three headline numbers are a row of stat tiles, and a handful of named
 * classes is a table. A grouped bar chart of "sent / interviews / offers" would
 * be three bars carrying less information than the three numbers themselves,
 * and a pie of two slices is the classic way to make a ratio harder to read.
 * The bars that do appear are the per-row rate meters in the tables, where a
 * length genuinely beats a number for scanning down a column.
 *
 * ## The distinction the whole screen turns on
 *
 * `ApplicationBoard`'s funnel bar counts where applications are **now**. These
 * count where they ever **got**. An application rejected after two interviews is
 * at REJECTED there and an interview here, and both are true — so the two
 * headings say which is which rather than leaving a reader to reconcile numbers
 * that look like they should match.
 *
 * ## A missing rate is not a zero
 *
 * Below the server's threshold the rate arrives as `null` and is rendered as an
 * em-dash with the reason beside it — never as 0%. One is "not enough happened
 * to say", the other is "enough happened, and none of it was this". Collapsing
 * them would tell somebody four applications in that their interview rate is
 * zero, which is both false and discouraging.
 */

function percent(rate: number): string {
  return `${Math.round(rate * 100)}%`
}

/**
 * One headline number.
 *
 * No `tabular-nums` on the value: it gives every digit the width of a zero,
 * which reads loose at display sizes. Tabular is for the columns below, where
 * digits have to line up down the page.
 */
function StatTile({
  label,
  value,
  note,
}: {
  label: string
  value: number
  note: string
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
      <p className="text-xs font-medium text-slate-600">{label}</p>
      <p className="mt-1 text-3xl font-semibold text-slate-900">{value}</p>
      <p className="mt-0.5 text-xs text-slate-500">{note}</p>
    </div>
  )
}

function rateNote(segment: FunnelSegment, rate: number | null, minimum: number): string {
  if (segment.applications === 0) return 'Nothing sent yet'
  if (rate === null) return `Rate needs ${minimum} applications`
  return `${percent(rate)} of applications`
}

/** A rate as a bar, or an em-dash when there is no rate to draw. */
function RateCell({ rate, applications }: { rate: number | null; applications: number }) {
  if (rate === null) {
    return (
      <td className="py-2 pl-3 text-right text-sm text-slate-400">
        {/* Not an empty bar and not a zero-width one. There is no measurement
            to draw — the same choice MatchBreakdown makes for an unscored
            dimension. */}
        <span aria-label="Not enough applications to show a rate">&mdash;</span>
      </td>
    )
  }
  return (
    <td className="py-2 pl-3">
      <div className="flex items-center justify-end gap-2">
        <div
          className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100"
          role="meter"
          aria-valuenow={Math.round(rate * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Interview rate over ${applications} applications`}
        >
          <div
            className="h-full rounded-full bg-slate-800"
            style={{ width: `${rate * 100}%` }}
          />
        </div>
        <span className="w-9 text-right text-sm tabular-nums text-slate-700">
          {percent(rate)}
        </span>
      </div>
    </td>
  )
}

function SegmentTable({
  caption,
  segments,
}: {
  caption: string
  segments: FunnelSegment[]
}) {
  if (segments.length === 0) return null

  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-900">{caption}</h3>
      {/* Tables are the one thing allowed to out-measure the page, inside their
          own scroller, rather than making the whole body scroll sideways. */}
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-md text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-xs text-slate-500">
              <th scope="col" className="py-1.5 text-left font-medium">
                {caption}
              </th>
              <th scope="col" className="py-1.5 pl-3 text-right font-medium">
                Sent
              </th>
              <th scope="col" className="py-1.5 pl-3 text-right font-medium">
                Interviews
              </th>
              <th scope="col" className="py-1.5 pl-3 text-right font-medium">
                Offers
              </th>
              <th scope="col" className="py-1.5 pl-3 text-right font-medium">
                Interview rate
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {segments.map((segment) => (
              <tr key={segment.label}>
                <th scope="row" className="py-2 text-left font-normal text-slate-900">
                  {segment.label}
                </th>
                {/* tabular-nums here, where digits stack down a column and
                    have to line up. */}
                <td className="py-2 pl-3 text-right tabular-nums text-slate-700">
                  {segment.applications}
                </td>
                <td className="py-2 pl-3 text-right tabular-nums text-slate-700">
                  {segment.interviews}
                </td>
                <td className="py-2 pl-3 text-right tabular-nums text-slate-700">
                  {segment.offers}
                </td>
                <RateCell rate={segment.interview_rate} applications={segment.applications} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function FunnelAnalytics() {
  const [data, setData] = useState<FunnelAnalyticsResponse | null>(null)
  const [failed, setFailed] = useState(false)

  const load = useCallback(async () => {
    try {
      setData(await applicationService.analytics())
      setFailed(false)
    } catch {
      setFailed(true)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (failed) {
    return (
      <section className={cardClass({ className: 'space-y-3' })}>
        <Alert tone="error" title="We couldn't work out how your applications have gone">
          Please try again.
        </Alert>
        <Button variant="secondary" size="sm" onClick={() => void load()}>
          Try again
        </Button>
      </section>
    )
  }

  if (data === null) {
    return (
      <section className={cardClass({ className: 'flex justify-center' })}>
        <Spinner className="size-6 text-indigo-600" label="Working out your rates" />
      </section>
    )
  }

  // Nothing sent means nothing to rate. The board below already explains the
  // empty state, and a row of zeroes above it would say the same thing worse.
  if (data.overall.applications === 0) return null

  const { overall, min_for_rate: minimum } = data

  return (
    <section
      aria-labelledby="outcomes-heading"
      className={cardClass()}
    >
      <h2 id="outcomes-heading" className="text-base font-semibold text-slate-900">
        How it has gone
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        Where your applications have <em>reached</em>, counted from the record of every move —
        so one rejected after an interview still counts as an interview.
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <StatTile
          label="Applications sent"
          value={overall.applications}
          note={overall.applications === 1 ? '1 job' : `${overall.applications} jobs`}
        />
        <StatTile
          label="Reached interview"
          value={overall.interviews}
          note={rateNote(overall, overall.interview_rate, minimum)}
        />
        <StatTile
          label="Reached offer"
          value={overall.offers}
          note={rateNote(overall, overall.offer_rate, minimum)}
        />
      </div>

      {overall.low_confidence && (
        <p className="mt-3 text-xs text-slate-500">
          Rates appear once you have {minimum} applications. Until then these are counts, not
          percentages — one interview in two applications is not a 50% success rate.
        </p>
      )}

      <div className="mt-6 space-y-6">
        <SegmentTable caption="Role" segments={data.by_role} />
        <SegmentTable caption="Location" segments={data.by_location} />
      </div>
    </section>
  )
}
