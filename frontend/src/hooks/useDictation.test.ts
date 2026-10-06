import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useDictation } from './useDictation'

/**
 * jsdom implements no recogniser, so every test builds one.
 *
 * Assigned onto `window` directly rather than spied, because `vi.spyOn` cannot
 * stub a missing property — the same approach `test/setup.ts` takes for
 * `matchMedia` and `useSpeech.test.ts` for the speech engine.
 */
interface FakeEngine {
  continuous: boolean
  interimResults: boolean
  lang: string
  start: ReturnType<typeof vi.fn>
  stop: ReturnType<typeof vi.fn>
  abort: ReturnType<typeof vi.fn>
  onresult: ((event: unknown) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
}

const built: FakeEngine[] = []

function installRecogniser() {
  built.length = 0
  ;(window as unknown as Record<string, unknown>).SpeechRecognition = function (
    this: FakeEngine,
  ) {
    this.continuous = false
    this.interimResults = false
    this.lang = ''
    this.start = vi.fn()
    this.stop = vi.fn()
    this.abort = vi.fn()
    this.onresult = null
    this.onerror = null
    this.onend = null
    built.push(this)
  }
  return built
}

function latest(): FakeEngine {
  const engine = built.at(-1)
  if (!engine) throw new Error('no recogniser was built')
  return engine
}

/** One `onresult` payload, in the shape the browser sends. */
function results(parts: { text: string; final: boolean }[]) {
  return {
    resultIndex: 0,
    results: parts.map((part) => {
      const entry = [{ transcript: part.text }] as unknown as ArrayLike<{
        transcript: string
      }> & { isFinal: boolean }
      entry.isFinal = part.final
      return entry
    }),
  }
}

describe('useDictation', () => {
  afterEach(() => {
    delete (window as unknown as Record<string, unknown>).SpeechRecognition
    delete (window as unknown as Record<string, unknown>).webkitSpeechRecognition
  })

  it('reports itself unsupported where there is no recogniser', () => {
    // jsdom, and Firefox, which has no implementation at all. The caller hides
    // the control on this.
    const { result } = renderHook(() => useDictation(vi.fn()))

    expect(result.current.supported).toBe(false)
  })

  it('does nothing when asked to start without one', () => {
    const onText = vi.fn()
    const { result } = renderHook(() => useDictation(onText))

    act(() => result.current.start())

    expect(result.current.listening).toBe(false)
    expect(onText).not.toHaveBeenCalled()
  })

  describe('with a recogniser', () => {
    it('hands up only the final transcript', () => {
      // Interim results rewrite themselves on every syllable. Committing them
      // would fight whatever the user was editing in the box.
      installRecogniser()
      const onText = vi.fn()
      const { result } = renderHook(() => useDictation(onText))
      act(() => result.current.start())

      act(() =>
        latest().onresult?.(
          results([
            { text: 'I would use dual writes', final: true },
            { text: 'and then verif', final: false },
          ]),
        ),
      )

      expect(onText).toHaveBeenCalledTimes(1)
      expect(onText).toHaveBeenCalledWith('I would use dual writes')
      expect(result.current.interim).toBe('and then verif')
    })

    it('asks for continuous recognition with interim results', () => {
      // Without `continuous` the browser stops at the first full stop, which is
      // useless for an answer that runs to a paragraph.
      installRecogniser()
      const { result } = renderHook(() => useDictation(vi.fn()))

      act(() => result.current.start())

      expect(latest().continuous).toBe(true)
      expect(latest().interimResults).toBe(true)
      expect(latest().lang.toLowerCase()).toContain('en')
    })

    it('keeps going when the browser stops on a pause', () => {
      /*
       * Chrome ends the session after a few seconds of quiet even with
       * `continuous`. Without a restart the microphone switches itself off
       * while somebody pauses mid-sentence to think, which is most of what
       * happens in an interview.
       */
      installRecogniser()
      const { result } = renderHook(() => useDictation(vi.fn()))
      act(() => result.current.start())

      act(() => latest().onend?.())

      expect(built).toHaveLength(2)
      expect(result.current.listening).toBe(true)
    })

    it('stays stopped once the user stops it', () => {
      installRecogniser()
      const { result } = renderHook(() => useDictation(vi.fn()))
      act(() => result.current.start())

      act(() => result.current.stop())
      act(() => latest().onend?.())

      expect(result.current.listening).toBe(false)
      expect(built).toHaveLength(1)
    })

    it('does not restart after a blocked microphone', () => {
      // The restart is what makes a pause survivable, and it is also what would
      // turn a refused permission into an endless retry.
      installRecogniser()
      const { result } = renderHook(() => useDictation(vi.fn()))
      act(() => result.current.start())

      act(() => latest().onerror?.({ error: 'not-allowed' }))
      act(() => latest().onend?.())

      expect(built).toHaveLength(1)
      expect(result.current.listening).toBe(false)
      expect(result.current.error).toMatch(/blocked the microphone/i)
    })

    it('treats silence as thinking, not as a failure', () => {
      // `no-speech` fires constantly while somebody considers their answer.
      installRecogniser()
      const { result } = renderHook(() => useDictation(vi.fn()))
      act(() => result.current.start())

      act(() => latest().onerror?.({ error: 'no-speech' }))

      expect(result.current.error).toBeNull()
      expect(result.current.listening).toBe(true)
    })

    it('explains a microphone that is not there', () => {
      installRecogniser()
      const { result } = renderHook(() => useDictation(vi.fn()))
      act(() => result.current.start())

      act(() => latest().onerror?.({ error: 'audio-capture' }))

      expect(result.current.error).toMatch(/no microphone/i)
    })

    it('releases the microphone when the component goes away', () => {
      // Otherwise it stays live after navigating off the interview, with the
      // browser's recording indicator on and nothing explaining it.
      installRecogniser()
      const { result, unmount } = renderHook(() => useDictation(vi.fn()))
      act(() => result.current.start())
      const engine = latest()

      unmount()

      expect(engine.abort).toHaveBeenCalled()
    })

    it('uses the latest callback without rebuilding the recogniser', () => {
      // The callback is a new closure on every keystroke. Rebuilding on it would
      // drop the microphone mid-sentence every time the box changed.
      installRecogniser()
      const first = vi.fn()
      const second = vi.fn()
      const { result, rerender } = renderHook(({ fn }) => useDictation(fn), {
        initialProps: { fn: first },
      })
      act(() => result.current.start())

      rerender({ fn: second })
      act(() => latest().onresult?.(results([{ text: 'spoken', final: true }])))

      expect(built).toHaveLength(1)
      expect(second).toHaveBeenCalledWith('spoken')
      expect(first).not.toHaveBeenCalled()
    })
  })
})
