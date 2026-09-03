import { api } from './apiClient'
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
   * Goes through the shared client like everything else. It used to use `fetch`
   * directly, on the reasoning that multipart needs the browser to generate its
   * own Content-Type — true, but the client now leaves a FormData body's header
   * alone, so the exemption bought nothing and cost three things: the 401
   * refresh (so an upload after an idle tab hard-failed and did not even log
   * the user out), the offline error mapping, and the correlation id on the
   * operation most likely to fail.
   */
  upload(file: File, title?: string): Promise<ResumeUploadResponse> {
    const form = new FormData()
    form.append('file', file)
    if (title !== undefined && title !== '') form.append('title', title)
    return api.post<ResumeUploadResponse>('/resumes', form)
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

  /**
   * Add a skill by id.
   *
   * `sourceVersionId` is passed when accepting a suggestion, which links the
   * skill to the resume it came from so it is removed with it. Omitted for a
   * skill added by hand, which is not about any particular document.
   */
  add(skillId: string, sourceVersionId?: string): Promise<CandidateSkill> {
    return api.post<CandidateSkill>('/profile/skills', {
      skill_id: skillId,
      ...(sourceVersionId !== undefined ? { source_version_id: sourceVersionId } : {}),
    })
  },

  /**
   * Add by name, creating the skill if the taxonomy does not know it.
   *
   * The server resolves aliases first, so typing "postgres" attaches to
   * PostgreSQL rather than creating a duplicate nothing else will match.
   */
  addByName(name: string): Promise<CandidateSkill> {
    return api.post<CandidateSkill>('/profile/skills', { skill_name: name })
  },

  remove(candidateSkillId: string): Promise<MessageResponse> {
    return api.delete<MessageResponse>(`/profile/skills/${candidateSkillId}`)
  },
}
