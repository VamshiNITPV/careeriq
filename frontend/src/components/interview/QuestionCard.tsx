import { PILL_SHAPE } from '@/components/ui/cardStyles'
import type { InterviewQuestion, QuestionDifficulty } from '@/types/interview'
import { cn } from '@/utils/cn'

const DIFFICULTY: Record<QuestionDifficulty, string> = {
  EASY: 'bg-slate-50 text-slate-700 ring-slate-200',
  MEDIUM: 'bg-sky-50 text-sky-800 ring-sky-200',
  HARD: 'bg-amber-50 text-amber-900 ring-amber-200',
  EXPERT: 'bg-rose-50 text-rose-800 ring-rose-200',
}

/**
 * One question, and why it was asked.
 *
 * `grounded_in` is shown deliberately. The question was built from the
 * candidate's own resume, and quoting the words it was built on turns "how did
 * it know that?" into something checkable — the grounding claim is inspectable
 * rather than taken on trust. It is also the honest thing to do: those are
 * their words, and they should be able to see the system read them.
 *
 * `expected_points` is shown *before* the answer is written, which is worth
 * pausing on. It looks like giving away the answer, and it is not what a real
 * interview does. But this is rehearsal: the rubric was fixed before any answer
 * existed, so showing it cannot change the mark, and somebody practising alone
 * with no idea what a strong answer contains is practising in the dark. It is
 * collapsed rather than hidden, so looking is a choice.
 */
export function QuestionCard({
  question,
  number,
  total,
}: {
  question: InterviewQuestion
  number: number
  total: number
}) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-slate-500">
          Question {number} of {total}
        </span>
        <span className={cn(PILL_SHAPE, 'bg-slate-50 text-slate-700 ring-slate-200')}>
          {question.topic}
        </span>
        <span className={cn(PILL_SHAPE, DIFFICULTY[question.difficulty])}>
          {question.difficulty.toLowerCase()}
        </span>
        {question.degraded && (
          // Said plainly rather than passed off. Personalisation was rejected
          // for this one, so it is a weaker question than the others, and the
          // candidate is owed that rather than being left to wonder why this
          // one felt generic.
          <span className={cn(PILL_SHAPE, 'bg-amber-50 text-amber-900 ring-amber-200')}>
            not personalised
          </span>
        )}
      </div>

      <p className="text-lg leading-relaxed font-medium text-slate-900">
        {question.question_text}
      </p>

      {question.grounded_in && (
        <p className="border-l-2 border-indigo-200 pl-3 text-sm text-slate-600">
          <span className="text-slate-500">Asked because your resume says: </span>
          <span className="italic">“{question.grounded_in}”</span>
        </p>
      )}

      {question.expected_points.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer list-none text-sm font-medium text-indigo-700 hover:text-indigo-800">
            <span className="group-open:hidden">What a strong answer covers</span>
            <span className="hidden group-open:inline">Hide what a strong answer covers</span>
          </summary>
          <ul className="mt-2 space-y-1 text-sm text-slate-600">
            {question.expected_points.map((point, index) => (
              <li key={index} className="flex gap-2">
                <span aria-hidden="true" className="text-slate-400">
                  •
                </span>
                <span>{point}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-slate-500">
            This was written before you answered, so reading it cannot change your mark.
          </p>
        </details>
      )}
    </div>
  )
}
