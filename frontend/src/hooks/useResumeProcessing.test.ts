import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resumeService } from '@/services/resumeService'
import type { ProcessingStatusResponse } from '@/types/resume'
import { useResumeProcessing } from './useResumeProcessing'

/**
 * The most intricate logic in the resume feature, and previously untested.
 *
 * Time control is the whole risk in this file. `poll()` awaits the status
 * request *before* arming the next setTimeout, so every advance must be
 * `vi.advanceTimersByTimeAsync` — the synchronous variant fires the timer
 * without letting the awaited promise settle, the next timer is never armed,
 * and the test either hangs or asserts against stale state.
 */

const POLL = 1200
const MAX_ATTEMPTS = 50

function status(overrides: Partial<ProcessingStatusResponse> = {}): ProcessingStatusResponse {
  return {
    version_id: 'v1',
    status: 'PARSING',
    percent: 65,
    stage_label: 'Finding sections and skills',
    error: null,
    is_terminal: false,
    ...overrides,
  }
}

const done = status({ status: 'COMPLETE', percent: 100, stage_label: 'Complete', is_terminal: true })

/** Let the immediate first poll settle. `track` calls it with no delay. */
async function settle() {
  await act(async () => {})
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe('useResumeProcessing', () => {
  beforeEach(() => {
    // setup.ts restores mocks per test, but timers are separate.
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('polls immediately, with no initial delay', async () => {
    const poll = vi.spyOn(resumeService, 'status').mockResolvedValue(status())
    const { result } = renderHook(() => useResumeProcessing())

    act(() => result.current.track('v1'))
    await settle()

    expect(poll).toHaveBeenCalledTimes(1)
    expect(result.current.progress?.stage_label).toBe('Finding sections and skills')
  })

  it('enters the polling phase synchronously', async () => {
    // Before the first response lands. Otherwise the page has nothing to show
    // for a whole round trip and falls back to the idle upload prompt, so the
    // panel visibly forgets the file that was just uploaded.
    vi.spyOn(resumeService, 'status').mockResolvedValue(status())
    const { result } = renderHook(() => useResumeProcessing())

    act(() => result.current.track('v1'))

    expect(result.current.phase).toBe('polling')
    expect(result.current.progress).toBeNull()
    await settle()
  })

  it('polls until terminal, then calls onDone exactly once and stops', async () => {
    const poll = vi
      .spyOn(resumeService, 'status')
      .mockResolvedValueOnce(status())
      .mockResolvedValueOnce(status({ percent: 85 }))
      .mockResolvedValue(done)
    const onDone = vi.fn()
    const { result } = renderHook(() => useResumeProcessing())

    act(() => result.current.track('v1', onDone))
    await settle()
    await advance(POLL * 2)

    expect(poll).toHaveBeenCalledTimes(3)
    expect(onDone).toHaveBeenCalledTimes(1)
    expect(onDone).toHaveBeenCalledWith(done)
    expect(result.current.phase).toBe('settled')

    // No further polls after a terminal status.
    await advance(POLL * 5)
    expect(poll).toHaveBeenCalledTimes(3)
  })

  it('times out after exactly MAX_ATTEMPTS polls', async () => {
    // Asserting the exact count pins the constant, so changing it is a
    // deliberate act rather than a silent one.
    const poll = vi.spyOn(resumeService, 'status').mockResolvedValue(status())
    const onDone = vi.fn()
    const { result } = renderHook(() => useResumeProcessing())

    act(() => result.current.track('v1', onDone))
    await settle()
    await advance(POLL * MAX_ATTEMPTS)

    expect(poll).toHaveBeenCalledTimes(MAX_ATTEMPTS)
    expect(result.current.phase).toBe('timedOut')
    expect(onDone).not.toHaveBeenCalled()
  })

  it('keeps the last progress after timing out', async () => {
    // The page shows the stage it got stuck at. Clearing it would snap the
    // panel back to "Drag a file here", which reads as "my upload vanished".
    vi.spyOn(resumeService, 'status').mockResolvedValue(status({ stage_label: 'Reading' }))
    const { result } = renderHook(() => useResumeProcessing())

    act(() => result.current.track('v1'))
    await settle()
    await advance(POLL * MAX_ATTEMPTS)

    expect(result.current.phase).toBe('timedOut')
    expect(result.current.progress?.stage_label).toBe('Reading')
  })

  it('retries a failed request rather than abandoning the job', async () => {
    const poll = vi
      .spyOn(resumeService, 'status')
      .mockRejectedValueOnce(new Error('network'))
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValue(done)
    const onDone = vi.fn()
    const { result } = renderHook(() => useResumeProcessing())

    act(() => result.current.track('v1', onDone))
    await settle()
    await advance(POLL * 2)

    expect(poll).toHaveBeenCalledTimes(3)
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('gives up on a permanently failing request, sharing the same budget', async () => {
    const poll = vi.spyOn(resumeService, 'status').mockRejectedValue(new Error('network'))
    const { result } = renderHook(() => useResumeProcessing())

    act(() => result.current.track('v1'))
    await settle()
    await advance(POLL * MAX_ATTEMPTS)

    expect(poll).toHaveBeenCalledTimes(MAX_ATTEMPTS)
    expect(result.current.phase).toBe('timedOut')
  })

  it('retry() resumes the same version with a fresh budget', async () => {
    const poll = vi.spyOn(resumeService, 'status').mockResolvedValue(status())
    const { result } = renderHook(() => useResumeProcessing())

    act(() => result.current.track('v9'))
    await settle()
    await advance(POLL * MAX_ATTEMPTS)
    expect(result.current.phase).toBe('timedOut')
    poll.mockClear()

    act(() => result.current.retry())
    await settle()

    expect(result.current.phase).toBe('polling')
    expect(poll).toHaveBeenCalledWith('v9')
  })

  it('reset() stops polling and clears everything', async () => {
    const poll = vi.spyOn(resumeService, 'status').mockResolvedValue(status())
    const { result } = renderHook(() => useResumeProcessing())

    act(() => result.current.track('v1'))
    await settle()
    act(() => result.current.reset())
    poll.mockClear()

    await advance(POLL * 10)

    expect(poll).not.toHaveBeenCalled()
    expect(result.current.progress).toBeNull()
    expect(result.current.phase).toBe('idle')
  })

  it('stops polling on unmount', async () => {
    // Otherwise a timer keeps firing against a component that no longer exists.
    const poll = vi.spyOn(resumeService, 'status').mockResolvedValue(status())
    const { result, unmount } = renderHook(() => useResumeProcessing())

    act(() => result.current.track('v1'))
    await settle()
    unmount()
    poll.mockClear()

    await advance(POLL * 10)

    expect(poll).not.toHaveBeenCalled()
  })

  it('a second track() cancels the first', async () => {
    const poll = vi.spyOn(resumeService, 'status').mockResolvedValue(status())
    const { result } = renderHook(() => useResumeProcessing())

    act(() => result.current.track('old'))
    await settle()
    act(() => result.current.track('new'))
    await settle()
    poll.mockClear()

    await advance(POLL * 3)

    expect(poll).not.toHaveBeenCalledWith('old')
    expect(poll).toHaveBeenCalledWith('new')
  })
})
