import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { jobService } from '@/services/jobService'
import type { MatchDimension, MatchDimensionName, MatchResponse } from '@/types/job'

const LABELS: Record<MatchDimensionName, string> = {
  semantic: 'Role fit',
  skill: 'Skills',
  experience: 'Experience',
  education: 'Education',
  location: 'Location',
  salary: 'Salary',
}

/**
 * How this reader matches this posting, and why (US-4.1, US-4.2).
 *
 * Sits directly under the job header rather than at the bottom next to
 * `SimilarJobs`. That section is an exit ramp — somewhere to go if this job is
 * wrong. This is the entry judgement, "should I read this at all", and it has
 * to arrive before the reader invests in the description.
 *
 * **Three rules hold this component together.**
 *
 * 1. *The number is never alone.* A score that four neutral dimensions helped
 *    produce, presented bare, claims a confidence the data does not support. The
 *    sentence under it says what share of the formula actually measured
 *    something — phrased about evidence, not points.
 *
 * 2. *Bars only on rows that measured something.* A half-filled bar at 0.5 is a
 *    picture of a mediocre result, and that is a lie: we did not measure
 *    mediocre, we measured nothing. Those rows get an em-dash instead. Their
 *    contribution is still printed, muted, because hiding it would break the
 *    arithmetic on screen — and the arithmetic adding up is the one thing this
 *    payload promises.
 *
 * 3. *A remedy only where one exists.* `NEEDS_PROFILE` rows link to the profile.
 *    `NEEDS_DATA` rows never do: the posting is missing something, or we have
 *    not indexed it yet, and neither is the reader's to fix.
 *
 * Like `SimilarJobs`, a rejected request renders nothing at all — with one
 * exception. `NO_RESUME` gets a real panel, because for a new account it is the
 * single most useful thing on the page.
 *
 * The cosine is never printed, here or anywhere.
 */
export function MatchBreakdown({ jobId }: { jobId: string }) {
  const [match, setMatch] = useState<MatchResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    setMatch(null)

    jobService.match(jobId).then(
      (response) => {
        if (!cancelled) setMatch(response)
      },
      () => {
        // Silent, as the similar-jobs section is. A reader should not be handed
        // an error box because a panel could not load.
      },
    )

    return () => {
      cancelled = true
    }
  }, [jobId])

  if (match === null) return null

  if (match.availability === 'NO_RESUME') {
    return (
      <section
        aria-labelledby="match-heading"
        className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6"
      >
        <h2 id="match-heading" className="text-base font-semibold text-slate-900">
          How you match
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Upload a resume and we&apos;ll score this posting against it, and show you exactly how the
          score was reached.
        </p>
        <Link
          to="/resume"
          className="mt-3 inline-block rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
        >
          Upload a resume
        </Link>
      </section>
    )
  }

  const informed = Math.round(Number(match.scored_weight) * 100)
  const fixable = match.breakdown.some((row) => row.status === 'NEEDS_PROFILE')

  return (
    <section
      aria-labelledby="match-heading"
      className="rounded-xl border border-slate-200 bg-white p-4 sm:p-6"
    >
      <h2 id="match-heading" className="text-base font-semibold text-slate-900">
        How you match
      </h2>

      <p className="mt-2 text-3xl font-semibold tabular-nums text-slate-900">
        {match.overall_score}
        <span className="text-base font-normal text-slate-500"> / 100</span>
      </p>
      {/*
        Deliberately the same visual weight as an ordinary line of body text,
        directly beneath the number rather than in a footnote. It is the caveat
        that makes the number honest, so it must not be findable only by someone
        who goes looking.
      */}
      <p className="mt-1 text-sm text-slate-600">
        {informed === 100
          ? 'Based on everything we compare.'
          : fixable
            ? `Based on ${informed}% of what we compare — the rest is waiting on your profile.`
            : `Based on ${informed}% of what we compare — the rest isn't stated here.`}
      </p>

      <ul className="mt-4 space-y-3">
        {match.breakdown.map((row) => (
          <Row key={row.dimension} row={row} />
        ))}
      </ul>
    </section>
  )
}

function Row({ row }: { row: MatchDimension }) {
  const scored = row.status === 'SCORED'
  const percent = Math.round(Number(row.score) * 100)

  return (
    <li>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium text-slate-800">{LABELS[row.dimension]}</span>
        {/*
          Printed on every row, including the ones that measured nothing —
          muted there, but present. Six visible numbers that add to the total is
          US-4.1 AC2 made checkable by eye; omitting four of them would leave a
          reader unable to reproduce the score from what is on screen.
        */}
        <span
          className={
            scored
              ? 'text-sm tabular-nums text-slate-700'
              : 'text-sm tabular-nums text-slate-400'
          }
        >
          {row.contribution}
        </span>
      </div>

      {scored ? (
        <div
          className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100"
          role="meter"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={LABELS[row.dimension]}
        >
          <div className="h-full rounded-full bg-slate-800" style={{ width: `${percent}%` }} />
        </div>
      ) : (
        // An em-dash, not an empty bar and not a half-full one. There is no
        // measurement to draw.
        <p className="mt-1 text-sm leading-none text-slate-300" aria-hidden="true">
          &mdash;
        </p>
      )}

      <p className="mt-1 text-xs text-slate-600">
        {row.reason}
        {row.status === 'NEEDS_PROFILE' && (
          <>
            {' '}
            <Link to="/profile" className="font-medium text-slate-900 underline">
              Update your profile
            </Link>
          </>
        )}
      </p>
    </li>
  )
}
