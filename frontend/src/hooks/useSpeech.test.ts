import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useSpeech } from './useSpeech'

/**
 * jsdom implements no speech engine at all, so every test here builds one.
 *
 * `vi.spyOn` cannot stub a missing property, which is why these are assigned
 * onto `window` directly and deleted afterwards — the same approach
 * `src/test/setup.ts` takes for `matchMedia`, and for the same reason.
 */
interface FakeEngine {
  speak: ReturnType<typeof vi.fn>
  cancel: ReturnType<typeof vi.fn>
  resume: ReturnType<typeof vi.fn>
  /** The last utterance handed to `speak`, so a test can end or fail it. */
  last: () => SpeechSynthesisUtterance | undefined
}

function installEngine(): FakeEngine {
  const spoken: SpeechSynthesisUtterance[] = []
  const engine = {
    speak: vi.fn((utterance: SpeechSynthesisUtterance) => spoken.push(utterance)),
    cancel: vi.fn(),
    resume: vi.fn(),
    last: () => spoken.at(-1),
  }
  // A constructor, because the hook calls `new SpeechSynthesisUtterance(text)`.
  ;(window as unknown as Record<string, unknown>).SpeechSynthesisUtterance = class {
    text: string
    onend: (() => void) | null = null
    onerror: (() => void) | null = null
    constructor(text: string) {
      this.text = text
    }
  }
  ;(window as unknown as Record<string, unknown>).speechSynthesis = engine
  return engine
}

function removeEngine() {
  delete (window as unknown as Record<string, unknown>).speechSynthesis
  delete (window as unknown as Record<string, unknown>).SpeechSynthesisUtterance
}

describe('useSpeech', () => {
  afterEach(() => {
    removeEngine()
    vi.useRealTimers()
  })

  describe('without an engine', () => {
    it('reports itself unsupported rather than throwing', () => {
      // jsdom, and any browser without speech. The caller hides the control on
      // this, so it must be a plain false and not an exception.
      const { result } = renderHook(() => useSpeech())

      expect(result.current.supported).toBe(false)
    })

    it('speaking is a no-op', () => {
      const { result } = renderHook(() => useSpeech())

      act(() => result.current.speak('anything'))

      expect(result.current.speaking).toBe(false)
    })
  })

  describe('with an engine', () => {
    let engine: FakeEngine

    beforeEach(() => {
      engine = installEngine()
    })

    it('reads the text it was given', () => {
      const { result } = renderHook(() => useSpeech())

      act(() => result.current.speak('What happens on a rebalance?'))

      expect(engine.speak).toHaveBeenCalledTimes(1)
      expect(engine.last()?.text).toBe('What happens on a rebalance?')
      expect(result.current.speaking).toBe(true)
    })

    it('cancels before starting, so a second click does not queue', () => {
      // Two utterances queue rather than replace. Without the cancel, clicking
      // twice reads the question through twice in a row.
      const { result } = renderHook(() => useSpeech())

      act(() => result.current.speak('first'))
      act(() => result.current.speak('second'))

      expect(engine.cancel).toHaveBeenCalledTimes(2)
      expect(engine.speak).toHaveBeenCalledTimes(2)
    })

    it('stops speaking when it reaches the end', () => {
      const { result } = renderHook(() => useSpeech())
      act(() => result.current.speak('a question'))

      act(() => engine.last()?.onend?.(new Event('end') as never))

      expect(result.current.speaking).toBe(false)
    })

    it('stops speaking when the utterance errors', () => {
      // `onerror` fires for an interrupted utterance too, and both mean the same
      // thing: nothing is being read any more. Without this the button would
      // stay on "Stop" forever.
      const { result } = renderHook(() => useSpeech())
      act(() => result.current.speak('a question'))

      act(() => engine.last()?.onerror?.(new Event('error') as never))

      expect(result.current.speaking).toBe(false)
    })

    it('stop cancels and clears the state', () => {
      const { result } = renderHook(() => useSpeech())
      act(() => result.current.speak('a question'))

      act(() => result.current.stop())

      expect(engine.cancel).toHaveBeenCalled()
      expect(result.current.speaking).toBe(false)
    })

    it('says nothing for empty text', () => {
      const { result } = renderHook(() => useSpeech())

      act(() => result.current.speak('   '))

      expect(engine.speak).not.toHaveBeenCalled()
    })

    it('falls silent when the component goes away', () => {
      // Speech outlives whatever started it. Without this, navigating away from
      // an interview leaves a disembodied voice finishing a question about Kafka.
      const { result, unmount } = renderHook(() => useSpeech())
      act(() => result.current.speak('a question'))
      engine.cancel.mockClear()

      unmount()

      expect(engine.cancel).toHaveBeenCalled()
    })

    it('nudges the engine so Chrome does not cut off mid-sentence', () => {
      /*
       * A long-standing Chromium bug pauses an utterance past roughly fifteen
       * seconds. Interview questions are two or three sentences, which lands on
       * that boundary, so this is a real failure rather than a theoretical one.
       */
      vi.useFakeTimers()
      const { result } = renderHook(() => useSpeech())

      act(() => result.current.speak('a long question'))
      act(() => void vi.advanceTimersByTime(25_000))

      expect(engine.resume).toHaveBeenCalled()
    })

    it('stops nudging once the reading has finished', () => {
      // Otherwise the interval outlives the utterance and resumes a queue that
      // nothing put anything into.
      vi.useFakeTimers()
      const { result } = renderHook(() => useSpeech())
      act(() => result.current.speak('a question'))
      act(() => engine.last()?.onend?.(new Event('end') as never))
      engine.resume.mockClear()

      act(() => void vi.advanceTimersByTime(30_000))

      expect(engine.resume).not.toHaveBeenCalled()
    })
  })
})
