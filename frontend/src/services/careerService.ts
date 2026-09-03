import { api } from './apiClient'
import type { MessageResponse } from '@/types/api'
import type { CareerKind, CareerSummary } from '@/types/career'

/**
 * Work history, education, projects and certifications.
 *
 * Generic over the four, matching the API: they differ only in their fields,
 * and four near-identical service objects would be four places to change when
 * the shape does.
 */
export const careerService = {
  /** All four in one request — the profile renders them on one screen. */
  summary(): Promise<CareerSummary> {
    return api.get<CareerSummary>('/profile/career')
  },

  create<T>(kind: CareerKind, payload: Record<string, unknown>): Promise<T> {
    return api.post<T>(`/profile/${kind}`, payload)
  },

  update<T>(kind: CareerKind, id: string, payload: Record<string, unknown>): Promise<T> {
    return api.patch<T>(`/profile/${kind}/${id}`, payload)
  },

  remove(kind: CareerKind, id: string): Promise<MessageResponse> {
    return api.delete<MessageResponse>(`/profile/${kind}/${id}`)
  },
}
