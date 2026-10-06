import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Speak an answer instead of typing it.
 *
 * The browser's own recogniser, for the same reason `useSpeech` uses its voice:
 * a cloud transcription service would be paid for out of the Gemini free tier
 * that already fails first, and this costs nothing.
 *
 * **What this is not.** `requirements.md` §3.2 rules out "video or audio
 * interview capture", and this does not do it: nothing records, nothing is
 * stored as audio, and the answer that reaches the server is the same text a
 * keyboard would have produced. The microphone is an input method here, not a
 * recording.
 *
 * Two facts worth knowing rather than discovering. In Chrome the audio is sent
 * to Google's speech service to be transcribed — it leaves the machine, even
 * though only text comes back. And Firefox has no implementation at all, so
 * `supported` is false there and the control does not appear.
 *
 * **Transcription is poor at exactly the vocabulary an interview answer is made
 * of** — "FastAPI", "p99", "idempotent" — and the answer is then marked on
 * technical correctness. So dictated text lands in the editable box rather than
 * being submitted, and the caller must keep it that way.
 */
export interface Dictation {
  /** False in Firefox, in jsdom, and anywhere without a recogniser. */
  supported: boolean
  listening: boolean
  /** Words being said right now, not yet final. Shown, never committed. */
  interim: string
  error: string | null
  start: () => void
  stop: () => void
}

/** The window properties, which TypeScript's DOM lib does not declare. */
interface RecognitionWindow {
  SpeechRecognition?: new () => SpeechRecognitionLike
  webkitSpeechRecognition?: new () => SpeechRecognitionLike
}

interface SpeechRecognitionLike {
  continuous: boolean
  interimResults: boolean
  lang: string
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
}

interface SpeechRecognitionEventLike {
  resultIndex: number
  results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>
}

/**
 * English, in whatever variety the browser is set to.
 *
 * `en-IN` transcribes Indian-accented English markedly better than `en-US`, and
 * the browser already knows which it is. Non-English locales fall back rather
 * than being honoured: the app is English-only (§3.2), and asking the recogniser
 * for Hindi would produce text nothing downstream can mark.
 */
function language(): string {
  const preferred = typeof navigator !== 'undefined' ? navigator.language : ''
  return preferred.toLowerCase().startsWith('en') ? preferred : 'en-US'
}

const MESSAGES: Record<string, string> = {
  'not-allowed': 'Your browser blocked the microphone. Allow it and try again.',
  'service-not-allowed': 'Your browser blocked the microphone. Allow it and try again.',
  'audio-capture': 'No microphone found.',
  network: 'The speech service could not be reached. You can still type.',
}

export function useDictation(onText: (text: string) => void): Dictation {
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')
  const [error, setError] = useState<string | null>(null)

  const recognition = useRef<SpeechRecognitionLike | null>(null)
  /** Whether the *user* wants it on, as opposed to whether it happens to be. */
  const wanted = useRef(false)
  // Held in a ref so restarting does not need the callback in a dependency
  // array, which would tear down and rebuild the recogniser on every keystroke.
  const onTextRef = useRef(onText)
  onTextRef.current = onText

  const factory =
    typeof window !== 'undefined'
      ? ((window as RecognitionWindow).SpeechRecognition ??
        (window as RecognitionWindow).webkitSpeechRecognition)
      : undefined

  const stop = useCallback(() => {
    wanted.current = false
    recognition.current?.stop()
    recognition.current = null
    setListening(false)
    setInterim('')
  }, [])

  const start = useCallback(() => {
    if (!factory) return
    setError(null)
    wanted.current = true

    const begin = () => {
      const engine = new factory()
      engine.continuous = true
      engine.interimResults = true
      engine.lang = language()

      engine.onresult = (event) => {
        let pending = ''
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const result = event.results[index]
          if (!result) continue
          const text = result[0]?.transcript ?? ''
          // Final results are handed up and appended; interim ones are only
          // displayed, because committing them would rewrite the box on every
          // syllable.
          if (result.isFinal) onTextRef.current(text)
          else pending += text
        }
        setInterim(pending)
      }

      engine.onerror = (event) => {
        // Silence is not a failure -- somebody is thinking. Everything else
        // stops, so a blocked microphone does not retry forever.
        if (event.error === 'no-speech' || event.error === 'aborted') return
        wanted.current = false
        setError(MESSAGES[event.error] ?? 'The microphone stopped working.')
        setListening(false)
        setInterim('')
      }

      engine.onend = () => {
        setInterim('')
        // Chrome ends the session after a few seconds of quiet even with
        // `continuous`, so without this the microphone switches itself off while
        // somebody pauses mid-sentence to think. Restarting only while the user
        // still wants it is what stops that becoming a loop after an error.
        if (wanted.current) begin()
        else setListening(false)
      }

      recognition.current = engine
      engine.start()
    }

    begin()
    setListening(true)
  }, [factory])

  // Stop on unmount, or the microphone stays live after navigating away.
  useEffect(() => () => {
    wanted.current = false
    recognition.current?.abort()
  }, [])

  return { supported: factory !== undefined, listening, interim, error, start, stop }
}
