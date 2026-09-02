import { useCallback, useEffect, useRef, useState } from 'react'
import { resumeService } from '@/services/resumeService'
import type { ProcessingStatusResponse } from '@/types/resume'

/**
 * Polls a resume version until parsing finishes.
 *
 * Polling, not a socket: ADR-010 specifies WebSockets for this, but the socket
 * arrives in Phase 10, and the API documents polling as the supported fallback.
 * Swapping later changes this hook only — nothing that uses it needs to know.
 */

const POLL_INTERVAL_MS = 1200
// Roughly a minute. The pipeline is seconds; a bounded loop means a stuck job
// reports a timeout instead of polling forever in a background tab.
const MAX_ATTEMPTS = 50

export function useResumeProcessing() {
  const [progress, setProgress] = useState<ProcessingStatusResponse | null>(null)
  const [timedOut, setTimedOut] = useState(false)
  const timer = useRef<number | null>(null)
  const attempts = useRef(0)

  const stop = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current)
      timer.current = null
    }
  }, [])

  // Clear on unmount. Without this, navigating away mid-parse leaves a timer
  // firing against an unmounted component.
  useEffect(() => stop, [stop])

  const track = useCallback(
    (versionId: string, onDone?: (final: ProcessingStatusResponse) => void) => {
      stop()
      attempts.current = 0
      setTimedOut(false)

      const poll = async () => {
        attempts.current += 1
        try {
          const status = await resumeService.status(versionId)
          setProgress(status)

          if (status.is_terminal) {
            onDone?.(status)
            return
          }
          if (attempts.current >= MAX_ATTEMPTS) {
            setTimedOut(true)
            return
          }
          timer.current = window.setTimeout(() => void poll(), POLL_INTERVAL_MS)
        } catch {
          // A transient failure should not abandon a job that is probably fine.
          // Retrying counts against the same budget, so this cannot loop
          // forever either.
          if (attempts.current < MAX_ATTEMPTS) {
            timer.current = window.setTimeout(() => void poll(), POLL_INTERVAL_MS)
          } else {
            setTimedOut(true)
          }
        }
      }

      void poll()
    },
    [stop],
  )

  const reset = useCallback(() => {
    stop()
    setProgress(null)
    setTimedOut(false)
  }, [stop])

  return { progress, timedOut, track, reset }
}
