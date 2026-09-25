import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Read text aloud with the browser's own speech engine.
 *
 * The browser rather than a cloud voice, and the reason is the free tier: the
 * same Gemini quota that writes the question would be paying for the audio, and
 * it is already the thing that fails first. A browser voice costs nothing, needs
 * no storage, adds no wait, and still works when the provider is down — which is
 * exactly when somebody is sitting on this page wondering what happened.
 *
 * The cost is honest: voice quality is whatever the operating system ships.
 *
 * **This is not an accessibility feature.** A screen reader already reads the
 * question, and it reads it better. This is for somebody who wants to hear an
 * interview question the way it would be asked, which is a different want.
 */
export interface Speech {
  /** False where the browser has no speech engine, and in jsdom. */
  supported: boolean
  speaking: boolean
  speak: (text: string) => void
  stop: () => void
}

/**
 * Chrome stops mid-sentence after roughly fifteen seconds.
 *
 * A long-standing Chromium bug: an utterance past that length is silently
 * paused. Interview questions are two or three sentences, which lands squarely
 * on the boundary, so this is a real failure and not a theoretical one. The
 * documented workaround is to nudge it. Harmless where the bug is absent —
 * `resume()` on something already playing does nothing.
 */
const KEEPALIVE_MS = 10_000

export function useSpeech(): Speech {
  const [speaking, setSpeaking] = useState(false)
  const keepalive = useRef<ReturnType<typeof setInterval> | null>(null)

  // Read once per render rather than cached: jsdom has no `speechSynthesis`, and
  // tests stub it onto `window` after this module is imported.
  const engine = typeof window !== 'undefined' ? window.speechSynthesis : undefined

  const clearKeepalive = useCallback(() => {
    if (keepalive.current !== null) {
      clearInterval(keepalive.current)
      keepalive.current = null
    }
  }, [])

  const stop = useCallback(() => {
    clearKeepalive()
    engine?.cancel()
    setSpeaking(false)
  }, [engine, clearKeepalive])

  const speak = useCallback(
    (text: string) => {
      if (!engine || !text.trim()) return

      // Cancel first, always. Two utterances queue rather than replace, so
      // without this a second click reads the question twice in a row.
      engine.cancel()
      clearKeepalive()

      const utterance = new SpeechSynthesisUtterance(text)
      utterance.onend = () => {
        clearKeepalive()
        setSpeaking(false)
      }
      // `onerror` fires for an interrupted utterance as well as a broken one, and
      // both mean the same thing here: nothing is being read any more.
      utterance.onerror = () => {
        clearKeepalive()
        setSpeaking(false)
      }

      setSpeaking(true)
      engine.speak(utterance)
      keepalive.current = setInterval(() => engine.resume(), KEEPALIVE_MS)
    },
    [engine, clearKeepalive],
  )

  // Silence on unmount. Speech outlives the component that started it, so
  // without this, navigating away leaves a disembodied voice finishing a
  // question about Kafka.
  useEffect(() => stop, [stop])

  return { supported: engine !== undefined, speaking, speak, stop }
}
