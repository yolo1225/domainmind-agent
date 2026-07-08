import { getData, postData } from './client'

export interface ResourceSummary {
  resource_id: string
  resource_type: string
  title: string
  content?: string
  difficulty: number
  review_status: string
  sources: string[]
  source_details?: Array<{ knowledge_id: string; name: string; source_title: string }>
  learner_profile_type?: string
  version?: number
  generation_task_id?: string | null
  generation_task_status?: string | null
  generation_decision?: string | null
  generated_at?: string | null
  task_created_at?: string | null
}

export function listResources() {
  return getData<ResourceSummary[]>('/resources')
}

export function submitFeedback(resourceId: string, feedbackType: string, rating = 3) {
  return postData(`/resources/${resourceId}/feedback`, {
    learner_id: 'learner_001',
    feedback_type: feedbackType,
    rating,
  })
}
