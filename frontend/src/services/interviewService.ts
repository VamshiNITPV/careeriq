import { api } from './apiClient'
import type {
  Interview,
  InterviewListResponse,
  InterviewStarted,
  StartInterviewRequest,
} from '@/types/interview'

export const interviewService = {
  /**
   * Start a session. The first question is generated after this returns.
   *
   * 202 with an id to poll, matching `POST /optimize/analyze` — a model call
   * takes seconds, and holding the request open for it makes every client's
   * timeout the server's problem.
   */
  start(body: StartInterviewRequest): Promise<InterviewStarted> {
    return api.post<InterviewStarted>('/interviews', body)
  },

  list(): Promise<InterviewListResponse> {
    return api.get<InterviewListResponse>('/interviews')
  },

  /**
   * Ask again after a failure that was nobody's fault.
   *
   * Refused with a 409 while a question is already waiting, because generation
   * appends and a second one would leave you two questions deep in a sequence
   * the policy believes is one.
   */
  retry(interviewId: string): Promise<InterviewStarted> {
    return api.post<InterviewStarted>(`/interviews/${interviewId}/retry`, {})
  },

  /** The session and its whole transcript. Also the poll target. */
  read(interviewId: string): Promise<Interview> {
    return api.get<Interview>(`/interviews/${interviewId}`)
  },

  /**
   * Record an answer. Marking it and asking the next question follow.
   *
   * The answer itself is written before the 202, so a slow provider cannot
   * lose what was typed — only the mark is deferred.
   */
  answer(
    interviewId: string,
    questionId: string,
    answerText: string,
    durationSeconds?: number,
  ): Promise<InterviewStarted> {
    return api.post<InterviewStarted>(
      `/interviews/${interviewId}/questions/${questionId}/answer`,
      { answer_text: answerText, duration_seconds: durationSeconds },
    )
  },
}
