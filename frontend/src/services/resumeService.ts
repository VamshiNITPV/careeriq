import { api, ApiError } from './apiClient'
import { getAccessToken } from './tokenStorage'
import type { MessageResponse } from '@/types/api'
import type {
  CandidateSkill,
  ProcessingStatusResponse,
  Resume,
  ResumeDetail,
  ResumeUploadResponse,
  Skill,
  SuggestionsResponse,
} from '@/types/resume'

const API_BASE = '/api/v1'

export const resumeService = {
  /**
   * Upload a resume.
   *
   * Uses `fetch` directly rather than the shared client because this is
   * multipart, not JSON: setting Content-Type by hand would omit the multipart
   * boundary and the server would reject the body. The browser must generate
   * that header itself.
   */
  async upload(file: File, title?: string): Promise<ResumeUploadResponse> {
    const form = new FormData()
    form.append('file', file)
    if (title !== undefined && title !== '') form.append('title', title)

    const token = getAccessToken()
    const response = await fetch(`${API_BASE}/resumes`, {
      method: 'POST',
      // Deliberately no Content-Type — see above.
      headers: token !== null ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    })

    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as {
        error?: { code: string; message: string; details?: Record<string, unknown> }
      } | null
      throw new ApiError(
        response.status,
        body?.error?.code ?? `HTTP_${response.status}`,
        body?.error?.message ?? 'Upload failed.',
        body?.error?.details ?? {},
      )
    }

    return (await response.json()) as ResumeUploadResponse
  },

  list(): Promise<Resume[]> {
    return api.get<Resume[]>('/resumes')
  },

  get(resumeId: string): Promise<ResumeDetail> {
    return api.get<ResumeDetail>(`/resumes/${resumeId}`)
  },

  status(versionId: string): Promise<ProcessingStatusResponse> {
    return api.get<ProcessingStatusResponse>(`/resumes/versions/${versionId}/status`)
  },

  /**
   * Re-run parsing on a file already uploaded.
   *
   * The skill taxonomy grows, so a resume parsed last week was parsed by an
   * older extractor. Corrections survive — the server refuses to overwrite any
   * skill the user has edited.
   */
  reparse(versionId: string): Promise<ResumeUploadResponse> {
    return api.post<ResumeUploadResponse>(`/resumes/versions/${versionId}/reparse`)
  },

  /** Inferred skills awaiting the user's confirmation. */
  suggestions(versionId: string): Promise<SuggestionsResponse> {
    return api.get<SuggestionsResponse>(`/resumes/versions/${versionId}/suggestions`)
  },

  rename(resumeId: string, title: string): Promise<Resume> {
    return api.patch<Resume>(`/resumes/${resumeId}`, { title })
  },

  setPrimary(resumeId: string): Promise<Resume> {
    return api.patch<Resume>(`/resumes/${resumeId}`, { is_primary: true })
  },

  remove(resumeId: string): Promise<MessageResponse> {
    return api.delete<MessageResponse>(`/resumes/${resumeId}`)
  },

  /** Absolute path for a download link. Auth is still required by the API. */
  downloadUrl(versionId: string): string {
    return `${API_BASE}/resumes/versions/${versionId}/download`
  },
}

export const skillService = {
  search(query: string): Promise<Skill[]> {
    return api.get<Skill[]>(`/skills/search?q=${encodeURIComponent(query)}`)
  },

  mySkills(): Promise<CandidateSkill[]> {
    return api.get<CandidateSkill[]>('/profile/skills')
  },

  add(skillId: string): Promise<CandidateSkill> {
    return api.post<CandidateSkill>('/profile/skills', { skill_id: skillId })
  },

  remove(candidateSkillId: string): Promise<MessageResponse> {
    return api.delete<MessageResponse>(`/profile/skills/${candidateSkillId}`)
  },
}
