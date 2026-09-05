import { api } from './apiClient'
import type { JobDetail, JobFilters, JobListResponse, JobSubmitResponse } from '@/types/job'

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
