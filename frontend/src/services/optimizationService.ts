import { api } from './apiClient'
import type { AnalysisResponse, AnalyzeStarted, ApplyResult } from '@/types/optimization'

export const optimizationService = {
  /**
   * Start tailoring a resume version to a job.
   *
   * Answers immediately with an id to poll. The model call happens after the
   * response, so nothing here waits on it.
   */
  analyze(resumeVersionId: string, jobId: string): Promise<AnalyzeStarted> {
    return api.post<AnalyzeStarted>('/optimize/analyze', {
      resume_version_id: resumeVersionId,
      job_id: jobId,
    })
  },

  read(analysisId: string): Promise<AnalysisResponse> {
    return api.get<AnalysisResponse>(`/optimize/${analysisId}`)
  },

  /**
   * Apply the accepted suggestions as a **new** resume version.
   *
   * Only the ids named are applied; everything else in the analysis is recorded
   * as rejected, so nothing re-offers text already passed over. The original
   * version is never changed.
   */
  apply(analysisId: string, acceptedIds: string[]): Promise<ApplyResult> {
    return api.post<ApplyResult>(`/optimize/${analysisId}/apply`, {
      accepted_suggestion_ids: acceptedIds,
    })
  },
}
