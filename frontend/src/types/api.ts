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

export type GenerationEventType =
  | 'trigger_routed'
  | 'agent_status'
  | 'feedback_classified'
  | 'profile_update_decided'
  | 'profile_updated'
  | 'profile_unchanged'
  | 'review_disagreement'
  | 'review_retrieval_started'
  | 'manual_review_required'
  | 'manual_review_resolved'
  | 'path_refresh_started'
  | 'path_refresh_completed'
  | 'resource_created'
  | 'task_completed'
  | 'task_failed'
  | 'unknown'

export interface AgentStatusEvent {
  event_type?: GenerationEventType
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
