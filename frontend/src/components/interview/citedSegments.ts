import type { CitedSpan } from '@/types/interview'

export interface Segment {
  text: string
  /** The citation covering this segment, or undefined for plain text between them. */
  span?: CitedSpan
  /** Position among the cited segments, for numbering the markers. */
  index?: number
}

/**
 * Split an answer into plain and cited stretches, in order.
 *
 * The server already verified every span against the answer — in range, not
 * inverted, and agreeing with its own quote. This does not re-check that, and
 * it does not use `span.text` at all: the rendered text always comes from the
 * answer at those offsets, so what the reader sees is what they wrote, and a
 * server that ever got sloppy about the quote could not change it.
 *
 * What this does handle is arrangement, which the server does not promise:
 *
 * **Spans arrive in whatever order the model listed them.** Rendering them
 * unsorted would emit the answer's paragraphs out of order, which looks like
 * data loss rather than a sorting bug.
 *
 * **Spans may overlap.** Two citations over the same words cannot both be
 * rendered without duplicating the text between them, and duplicated words in
 * somebody's own answer read as though the system rewrote it. The earlier span
 * wins and the overlapping one is dropped — the feedback loses a marker, which
 * is a smaller wrong than the answer appearing to say something twice.
 *
 * Anything out of range is skipped rather than clamped. Clamping would move a
 * citation onto words it was never about, and a citation pointing somewhere
 * other than where it says is worse than no citation, because it will be
 * believed.
 */
export function citedSegments(text: string, spans: CitedSpan[] | null): Segment[] {
  if (!spans || spans.length === 0) return [{ text }]

  const usable = spans
    .filter((span) => span.start >= 0 && span.end > span.start && span.end <= text.length)
    .sort((a, b) => a.start - b.start)

  const segments: Segment[] = []
  let cursor = 0
  let index = 0

  for (const span of usable) {
    if (span.start < cursor) continue // overlaps one already rendered
    if (span.start > cursor) segments.push({ text: text.slice(cursor, span.start) })
    segments.push({ text: text.slice(span.start, span.end), span, index })
    cursor = span.end
    index += 1
  }

  if (cursor < text.length) segments.push({ text: text.slice(cursor) })
  return segments
}
