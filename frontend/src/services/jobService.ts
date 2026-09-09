import { api } from './apiClient'
import type {
  JobDetail,
  JobFilters,
  JobListResponse,
  JobSubmitResponse,
  MatchResponse,
  RecommendationsResponse,
  SimilarJobsResponse,
} from '@/types/job'

export const jobService = {
  /**
   * Browse live postings.
   *
   * Empty and undefined filters are dropped rather than sent as blanks: the
   * API treats `?q=` as a search for the empty string, which matches
   * everything but takes the ILIKE path to get there.
   */
  list(filters: JobFilters = {}): Promise<JobListResponse> {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== '') params.set(key, String(value))
    }
    const query = params.toString()
    return api.get<JobListResponse>(`/jobs${query ? `?${query}` : ''}`)
  },

  /**
   * Nearest neighbours by embedding.
   *
   * A side section, not a page: callers must treat a rejection as "render
   * nothing", never as a page-level error.
   */
  similar(jobId: string, limit = 6): Promise<SimilarJobsResponse> {
    return api.get<SimilarJobsResponse>(`/jobs/${jobId}/similar?limit=${limit}`)
  },

  /**
   * This caller's explainable score for one job.
   *
   * Always resolves with a payload when the request succeeds — `availability`
   * carries the "we couldn't" cases rather than an error status, so a rejection
   * here means the network or the session, never "no match".
   */
  match(jobId: string): Promise<MatchResponse> {
    return api.get<MatchResponse>(`/jobs/${jobId}/match`)
  },

  /**
   * Jobs ranked for the signed-in user.
   *
   * `cursor` is whatever the previous response returned — opaque, and passed
   * back verbatim. Parsing it here would freeze the server's sort key against a
   * client it cannot see.
   */
  recommendations(
    options: { limit?: number; cursor?: string } = {},
  ): Promise<RecommendationsResponse> {
    const params = new URLSearchParams()
    if (options.limit !== undefined) params.set('limit', String(options.limit))
    if (options.cursor !== undefined) params.set('cursor', options.cursor)
    const query = params.toString()
    return api.get<RecommendationsResponse>(`/recommendations${query ? `?${query}` : ''}`)
  },

  get(jobId: string): Promise<JobDetail> {
    return api.get<JobDetail>(`/jobs/${jobId}`)
  },

  /**
   * Paste a description.
   *
   * Returns the parsed job directly — parsing is synchronous server-side, so
   * unlike a resume upload there is nothing to poll for.
   */
  submit(input: {
    description: string
    title?: string
    company?: string
    /** Required: this becomes the "Apply for this job" link on the detail page. */
    source_url: string
  }): Promise<JobSubmitResponse> {
    return api.post<JobSubmitResponse>('/jobs', input)
  },

  /**
   * Attach an application link to a job that has none.
   *
   * Set-only-when-null server-side, so this rejects with 409 rather than
   * replacing a link someone else already added.
   */
  setApplicationLink(jobId: string, sourceUrl: string): Promise<JobDetail> {
    return api.patch<JobDetail>(`/jobs/${jobId}/application-link`, { source_url: sourceUrl })
  },
}
