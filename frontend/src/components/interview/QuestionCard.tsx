import { PILL_SHAPE } from '@/components/ui/cardStyles'
import { useSpeech } from '@/hooks/useSpeech'
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
  // One engine per card, so each question's button controls only its own
  // reading -- and starting one cancels whatever else was playing, because the
  // engine itself is shared by the page.
  const speech = useSpeech()

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

      <div className="flex items-start gap-3">
        <p className="flex-1 text-lg leading-relaxed font-medium text-slate-900">
          {question.question_text}
        </p>
        {/* Beside the question, not under it: the point is to hear *this*, and a
            control parked at the bottom of a card reads as belonging to the card
            rather than to the sentence. Hidden entirely where the browser has no
            speech engine -- a disabled button invites a click that can never
            work and explains nothing. */}
        {speech.supported && (
          <button
            type="button"
            onClick={() =>
              speech.speaking ? speech.stop() : speech.speak(question.question_text)
            }
            // The label carries the state rather than aria-pressed: "Stop" says
            // what the click does, where a pressed "Listen" makes the reader
            // work out what pressed means.
            className="shrink-0 rounded-md px-2 py-1 text-sm font-medium text-indigo-700 ring-1 ring-indigo-200 transition-colors hover:bg-indigo-50"
          >
            {speech.speaking ? 'Stop' : 'Listen'}
          </button>
        )}
      </div>

      {/*
        Three states, not two, and the third was invisible until a live run
        surfaced it.

        A question can be grounded in the resume, or degraded because a claimed
        grounding failed verification, or simply ungrounded — the model was
        given the resume and volunteered no connection to it. That last is not a
        failure: asked to build an AI Engineer question on a backend engineer's
        payments resume, declining to link them is the fabrication guard working
        rather than breaking. But a page whose headline claim is "built from
        your resume" cannot show that question in silence, because silence reads
        as the grounded case with the quote left off.
      */}
      {question.grounded_in ? (
        <p className="border-l-2 border-indigo-200 pl-3 text-sm text-slate-600">
          <span className="text-slate-500">Asked because your resume says: </span>
          <span className="italic">“{question.grounded_in}”</span>
        </p>
      ) : (
        !question.degraded && (
          <p className="border-l-2 border-slate-200 pl-3 text-sm text-slate-500">
            A general question for this role — nothing in your resume lines up with this topic
            closely enough to build on, and inventing a link is the one thing this will not do.
          </p>
        )
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
