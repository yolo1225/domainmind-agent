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

export type AgentEventPayload = Record<string, unknown>

export interface AgentStatusEvent {
  run_id?: number
  task_id: string
  step: string
  status: string
  agent_name?: string
  generation_round?: number | null
  is_revision_round?: boolean
  event_message?: string
  payload?: AgentEventPayload
  timestamp?: string | null
  decision?: string
}
