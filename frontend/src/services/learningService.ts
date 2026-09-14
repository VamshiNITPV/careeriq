import { api } from './apiClient'
import type { LearningPathResponse } from '@/types/learning'

export const learningService = {
  /**
   * The ordered study plan derived from your current gaps.
   *
   * Derived per request, so it reflects today's profile and today's corpus. What
   * persists is the ticks — a decision has to outlive a recomputation.
   */
  path(jobId?: string): Promise<LearningPathResponse> {
    return api.get<LearningPathResponse>(
      `/skills/learning-path${jobId ? `?job_id=${jobId}` : ''}`,
    )
  },

  /**
   * Tick a step off, or put it back.
   *
   * The body carries the desired end state rather than naming an action, so
   * repeating it changes nothing — this is a checkbox, and a double tap on a
   * phone must not become an error.
   */
  setCompleted(skillId: string, completed: boolean): Promise<{ message: string }> {
    return api.put<{ message: string }>(`/skills/learning-path/steps/${skillId}`, { completed })
  },
}
