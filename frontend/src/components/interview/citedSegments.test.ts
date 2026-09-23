import { describe, expect, it } from 'vitest'
import { citedSegments } from './citedSegments'
import type { CitedSpan } from '@/types/interview'

const ANSWER = 'I used dual writes during the cutover, then verified row counts matched.'

function span(start: number, end: number, note = ''): CitedSpan {
  return { start, end, text: ANSWER.slice(start, end), note }
}

/** Offsets derived from the word, so a miscount cannot quietly change a case. */
function spanOf(word: string): CitedSpan {
  const start = ANSWER.indexOf(word)
  if (start < 0) throw new Error(`${word} is not in the answer`)
  return span(start, start + word.length)
}

const DUAL_WRITES = spanOf('dual writes')
const VERIFIED = spanOf('verified')

describe('citedSegments', () => {
  it('returns the whole answer when nothing is cited', () => {
    expect(citedSegments(ANSWER, null)).toEqual([{ text: ANSWER }])
    expect(citedSegments(ANSWER, [])).toEqual([{ text: ANSWER }])
  })

  it('splits around a single citation', () => {
    const segments = citedSegments(ANSWER, [DUAL_WRITES])

    expect(segments.map((s) => s.text)).toEqual([
      'I used ',
      'dual writes',
      ' during the cutover, then verified row counts matched.',
    ])
    expect(segments[1]?.span).toBeDefined()
    expect(segments[0]?.span).toBeUndefined()
  })

  it('reassembles into exactly the original answer', () => {
    // The property that matters: whatever the arrangement, nothing is added,
    // dropped or reordered. A reader has to be able to trust that the text on
    // screen is the text they typed.
    const cases: CitedSpan[][] = [
      [span(0, 6)],
      [DUAL_WRITES, VERIFIED],
      [VERIFIED, DUAL_WRITES],
      [span(0, ANSWER.length)],
    ]

    for (const spans of cases) {
      expect(citedSegments(ANSWER, spans).map((s) => s.text).join('')).toBe(ANSWER)
    }
  })

  it('sorts spans that arrive out of order', () => {
    // The model lists them in whatever order it thought of them. Rendering
    // unsorted would emit the answer's own words out of order, which looks
    // like data loss rather than a sorting bug.
    const segments = citedSegments(ANSWER, [VERIFIED, DUAL_WRITES])

    expect(segments.map((s) => s.text).join('')).toBe(ANSWER)
    expect(segments.filter((s) => s.span).map((s) => s.text)).toEqual([
      'dual writes',
      'verified',
    ])
  })

  it('numbers the citations in reading order, not the order given', () => {
    const segments = citedSegments(ANSWER, [VERIFIED, DUAL_WRITES])
    const cited = segments.filter((s) => s.span)

    expect(cited.map((s) => s.index)).toEqual([0, 1])
  })

  it('drops a span overlapping one already rendered', () => {
    // Two citations over the same words cannot both be shown without repeating
    // the text between them, and duplicated words in somebody's own answer read
    // as though the system rewrote it. Losing a marker is the smaller wrong.
    const segments = citedSegments(ANSWER, [DUAL_WRITES, span(12, 25)])

    expect(segments.map((s) => s.text).join('')).toBe(ANSWER)
    expect(segments.filter((s) => s.span)).toHaveLength(1)
  })

  it('keeps a span that merely touches the end of the last one', () => {
    // Adjacent is not overlapping, and dropping it would lose a valid citation.
    const segments = citedSegments(ANSWER, [span(0, 6), span(6, 18)])

    expect(segments.filter((s) => s.span)).toHaveLength(2)
    expect(segments.map((s) => s.text).join('')).toBe(ANSWER)
  })

  it.each([
    ['past the end', { start: 0, end: 9999, text: '', note: '' }],
    ['negative', { start: -1, end: 5, text: '', note: '' }],
    ['inverted', { start: 20, end: 10, text: '', note: '' }],
    ['empty', { start: 5, end: 5, text: '', note: '' }],
  ])('skips a %s span rather than clamping it', (_label, bad) => {
    // Clamping would move a citation onto words it was never about, and a
    // citation pointing somewhere other than where it says will be believed.
    const segments = citedSegments(ANSWER, [bad])

    expect(segments).toEqual([{ text: ANSWER }])
  })

  it('renders the answer text, never the span text', () => {
    // The offsets are the truth and `span.text` is a copy. The server checks
    // they agree; this makes it impossible for a disagreement to reach a
    // reader even if it ever stopped.
    const lying: CitedSpan = { start: 7, end: 18, text: 'something else', note: '' }

    const segments = citedSegments(ANSWER, [lying])

    expect(segments[1]?.text).toBe('dual writes')
    expect(segments.map((s) => s.text).join('')).toBe(ANSWER)
  })
})
