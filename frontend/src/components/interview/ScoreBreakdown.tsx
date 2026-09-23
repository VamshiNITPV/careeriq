import { DIMENSIONS, type AnswerScore, type Dimension } from '@/types/interview'
import { cn } from '@/utils/cn'

/** What each dimension means, in the candidate's terms rather than the rubric's. */
const MEANING: Record<Dimension, string> = {
  technical: 'Is it correct?',
  relevance: 'Does it answer the question asked?',
  completeness: 'Does it cover what a strong answer covers?',
  communication: 'Is it clearly expressed?',
  structure: 'Does it hold together?',
}

const FIELD: Record<Dimension, keyof AnswerScore> = {
  technical: 'technical_score',
  relevance: 'relevance_score',
  completeness: 'completeness_score',
  communication: 'communication_score',
  structure: 'structure_score',
}

/**
 * Bands, not a gradient.
 *
 * A continuous colour ramp gives 0.61 and 0.59 visibly different bars and
 * implies the scorer can tell them apart. It cannot — the evaluation targets a
 * mean absolute error of 0.15, so two marks within a band of each other are the
 * same judgement. Three bands say only what the measurement supports.
 */
function band(value: number): { bar: string; label: string } {
  if (value >= 0.7) return { bar: 'bg-emerald-500', label: 'text-emerald-700' }
  if (value >= 0.4) return { bar: 'bg-amber-500', label: 'text-amber-700' }
  return { bar: 'bg-rose-500', label: 'text-rose-700' }
}

function asNumber(value: string): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

/** A mark out of 10, because "7/10" is a sentence and "0.7" is a measurement. */
function outOfTen(value: number): string {
  return (Math.round(value * 100) / 10).toFixed(1)
}

export function ScoreBreakdown({ score }: { score: AnswerScore }) {
  const overall = asNumber(score.overall_score)

  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-2">
        <span
          className={cn('text-3xl font-bold tabular-nums', band(overall).label)}
        >
          {outOfTen(overall)}
        </span>
        <span className="text-sm text-slate-500">out of 10 overall</span>
      </div>

      <dl className="space-y-2.5">
        {DIMENSIONS.map((name) => {
          const value = asNumber(score[FIELD[name]] as string)
          const tone = band(value)
          return (
            <div key={name} className="grid grid-cols-[8rem_1fr_2.5rem] items-center gap-3">
              <dt className="text-sm text-slate-700 capitalize" title={MEANING[name]}>
                {name}
              </dt>
              {/* The bar is decoration over a number that is already readable,
                  so it is hidden from assistive tech rather than announced as a
                  second, wordless copy of the same value. */}
              <div className="h-1.5 rounded-full bg-slate-100" aria-hidden="true">
                <div
                  className={cn('h-1.5 rounded-full', tone.bar)}
                  style={{ width: `${Math.max(2, value * 100)}%` }}
                />
              </div>
              <dd className="text-right text-sm font-medium tabular-nums text-slate-700">
                {outOfTen(value)}
              </dd>
            </div>
          )
        })}
      </dl>

      <p className="text-xs text-slate-500">
        The overall mark is the average of the five. It is computed here, not asked of
        the model, so the parts and the whole cannot disagree.
      </p>
    </div>
  )
}
