import { citedSegments } from './citedSegments'
import type { CitedSpan } from '@/types/interview'

/**
 * The candidate's answer, with the parts the feedback points at marked.
 *
 * This is where the offset checking on the server becomes something a person
 * can see. The feedback says "you covered the technique but not the rollback",
 * and the highlight shows exactly which words it means — rather than a
 * paragraph of assessment floating free of the text it is about.
 *
 * The marked text always comes from the answer at the cited offsets, never from
 * the model's copy of it. The server verifies the two agree; rendering from the
 * answer means a disagreement could not reach the reader even if that check
 * ever stopped working.
 */
export function CitedAnswer({
  text,
  spans,
}: {
  text: string
  spans: CitedSpan[] | null
}) {
  const segments = citedSegments(text, spans)
  const cited = segments.filter((segment) => segment.span)

  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed whitespace-pre-wrap text-slate-800">
        {segments.map((segment, position) =>
          segment.span ? (
            <mark
              key={position}
              className="rounded bg-indigo-100 px-0.5 text-slate-900 ring-1 ring-indigo-200"
            >
              {segment.text}
              <sup className="ml-0.5 text-[0.65rem] font-semibold text-indigo-700">
                {(segment.index ?? 0) + 1}
              </sup>
            </mark>
          ) : (
            // A plain fragment, so the text is one continuous run rather than a
            // sequence of spans the browser might break differently.
            <span key={position}>{segment.text}</span>
          ),
        )}
      </p>

      {cited.length > 0 && (
        <ol className="space-y-1.5 text-xs text-slate-600">
          {cited.map((segment, position) => (
            <li key={position} className="flex gap-2">
              <span className="font-semibold text-indigo-700">{position + 1}.</span>
              {/* A citation with no note still earns its highlight: it says
                  "this is the part being talked about", which is most of the
                  value. Nothing is invented to fill the gap. */}
              <span>{segment.span?.note || 'Referred to in the feedback above.'}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
