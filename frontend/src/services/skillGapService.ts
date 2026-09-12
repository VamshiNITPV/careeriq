import { api } from './apiClient'
import type { SkillGapsResponse } from '@/types/skillGap'

export const skillGapService = {
  /**
   * What the target asks for that you do not have.
   *
   * With no `jobId` this aggregates across the target roles on your profile;
   * with one it narrows to that posting. The server runs the same computation
   * either way, so the single-job answer cannot disagree with the aggregate
   * that contains it.
   *
   * Always resolves with a payload when the request succeeds — `availability`
   * carries the "we couldn't" cases rather than an error status, so a rejection
   * here means the network or the session, never "no gaps".
   */
  gaps(jobId?: string): Promise<SkillGapsResponse> {
    return api.get<SkillGapsResponse>(`/skills/gaps${jobId ? `?job_id=${jobId}` : ''}`)
  },
}
