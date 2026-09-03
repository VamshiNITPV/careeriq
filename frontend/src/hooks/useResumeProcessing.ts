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

/**
 * An explicit phase rather than a `timedOut` boolean beside `progress`.
 *
 * With two independent values the page could render two contradictory things at
 * once — and did: on timeout the warning appeared *over* a progress bar that
 * was still animating, because `progress` was untouched and its `is_terminal`
 * was still false.
 */
export type ProcessingPhase = 'idle' | 'polling' | 'settled' | 'timedOut'

export function useResumeProcessing() {
  const [progress, setProgress] = useState<ProcessingStatusResponse | null>(null)
  const [phase, setPhase] = useState<ProcessingPhase>('idle')
  const timer = useRef<number | null>(null)
  const attempts = useRef(0)
  // What retry() re-runs. Kept in a ref so retry has a stable identity and does
  // not re-create itself every time a poll lands.
  const tracking = useRef<{
    versionId: string
    onDone?: ((final: ProcessingStatusResponse) => void) | undefined
  } | null>(null)

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
      tracking.current = { versionId, onDone }
      // Set synchronously, before the first await. Otherwise there is a whole
      // round trip between the 202 and the first status response during which
      // the page has nothing to show and falls back to the idle upload prompt —
      // so the panel visibly forgets the file that was just uploaded.
      setPhase('polling')

      const poll = async () => {
        attempts.current += 1
        try {
          const status = await resumeService.status(versionId)
          setProgress(status)

          if (status.is_terminal) {
            setPhase('settled')
            onDone?.(status)
            return
          }
          if (attempts.current >= MAX_ATTEMPTS) {
            setPhase('timedOut')
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
            setPhase('timedOut')
          }
        }
      }

      void poll()
    },
    [stop],
  )

  /**
   * Poll the same version again with a fresh budget.
   *
   * Turns the timeout from a dead end into a button. The alternative on offer
   * was "refresh the page to check again", which does nothing useful — a
   * reload shows no processing state at all.
   */
  const retry = useCallback(() => {
    const current = tracking.current
    if (current === null) return
    track(current.versionId, current.onDone)
  }, [track])

  const reset = useCallback(() => {
    stop()
    tracking.current = null
    setProgress(null)
    setPhase('idle')
  }, [stop])

  return { progress, phase, track, retry, reset }
}
