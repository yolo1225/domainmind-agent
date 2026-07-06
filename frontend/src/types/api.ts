export interface ApiResponse<T> {
  schema_version: string
  request_id: string
  data: T
  error: null | {
    code: string
    message: string
    details?: Record<string, unknown>
  }
  timestamp: string
}

export type ResourceType = 'lecture' | 'practice_guide' | 'graded_quiz'

export interface AgentStatusEvent {
  task_id: string
  step: string
  status: string
}
