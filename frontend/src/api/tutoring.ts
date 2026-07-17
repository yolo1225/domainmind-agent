import { getData, postData } from './client'

export interface TutoringSession {
  session_id: string
  status: string
  turn_count: number
  messages: Array<{
    message_id: string
    sender: string
    message_type: string
    content: string
    created_at: string | null
  }>
}

export function createTutoringSession(resourceId: string, learnerId = 'learner_001') {
  return postData<TutoringSession>('/tutoring/sessions', {
    resource_id: resourceId,
    learner_id: learnerId,
  })
}

export function sendTutoringMessage(sessionId: string, content: string) {
  return postData<{
    session_id: string
    reply: { message_id: string; message_type: string; content: string }
    feedback_intent: string
    recommended_action: string
    profile_update_required: boolean
    decision_reason: string
    task_id: string | null
  }>(`/tutoring/sessions/${sessionId}/messages`, { content })
}

export function getTutoringSession(sessionId: string) {
  return getData<TutoringSession>(`/tutoring/sessions/${sessionId}`)
}
