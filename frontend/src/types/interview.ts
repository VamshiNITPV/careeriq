export type InterviewStatus = 'CREATED' | 'IN_PROGRESS' | 'COMPLETED' | 'ABANDONED'
export type QuestionDifficulty = 'EASY' | 'MEDIUM' | 'HARD' | 'EXPERT'

/** The five the answer is marked on, in the order they are shown. */
export const DIMENSIONS = [
  'technical',
  'relevance',
  'completeness',
  'communication',
  'structure',
] as const

export type Dimension = (typeof DIMENSIONS)[number]

/**
 * A part of the answer the feedback points at.
 *
 * `start` and `end` are character offsets into the answer, verified against it
 * on the server before this was stored, and `text` is what was found there
 * rather than what the model said it quoted. Both are sent so the UI can
 * highlight without trusting either on its own.
 */
export interface CitedSpan {
  start: number
  end: number
  text: string
  note: string
}

export interface AnswerScore {
  /** Decimals arrive as strings; Postgres NUMERIC does not fit a JS number safely. */
  technical_score: string
  relevance_score: string
  completeness_score: string
  communication_score: string
  structure_score: string
  /** The mean of the five, computed on the server so the parts and the whole agree. */
  overall_score: string
  feedback: string | null
  strengths: string[]
  improvements: string[]
  cited_spans: CitedSpan[] | null
  /** What the policy decided next, recorded when the score was. */
  next_difficulty: QuestionDifficulty | null
}

export interface InterviewAnswer {
  answer_text: string
  duration_seconds: number | null
  submitted_at: string | null
  /** Null while the marking is still running, and after it has failed. */
  score: AnswerScore | null
}

export interface InterviewQuestion {
  id: string
  question_order: number
  question_text: string
  topic: string
  difficulty: QuestionDifficulty
  /** The rubric the answer is marked against, written before it existed. */
  expected_points: string[]
  /** The resume words this was built on, if any. */
  grounded_in: string | null
  /** True when personalisation was rejected and this is the topic-only fallback. */
  degraded: boolean
  asked_at: string | null
  answer: InterviewAnswer | null
}

export interface Interview {
  id: string
  target_role: string
  target_job_id: string | null
  status: InterviewStatus
  current_difficulty: QuestionDifficulty
  topics_covered: string[]
  questions_asked: number
  question_budget: number
  questions: InterviewQuestion[]
  created_at: string
  /**
   * Why no question arrived, when none has.
   *
   * Generation runs after the response is sent, so a failure has no request
   * left to fail on. This is the difference between "still thinking" and "this
   * will never finish", and a client polling forever on the second is the
   * failure worth designing against.
   */
  summary_feedback: string | null
}

export interface InterviewSummary {
  id: string
  target_role: string
  status: InterviewStatus
  questions_asked: number
  question_budget: number
  /** Not the same as `questions_asked`: the last one sits unanswered while you think. */
  answered: number
  /** Null when nothing is marked yet — never 0, which would read as having done badly. */
  average_score: string | null
  created_at: string
}

export interface InterviewListResponse {
  items: InterviewSummary[]
  total: number
}

export interface InterviewStarted {
  interview_id: string
  status: InterviewStatus
  poll_url: string
}

export interface StartInterviewRequest {
  target_role: string
  target_job_id?: string
  question_budget?: number
}
