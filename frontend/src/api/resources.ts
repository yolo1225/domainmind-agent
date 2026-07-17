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
  is_current?: boolean
  generation_task_id?: string | null
  generation_task_status?: string | null
  generation_decision?: string | null
  generated_at?: string | null
  task_created_at?: string | null
}

export function listResources() {
  return getData<ResourceSummary[]>('/resources')
}

export function listResourceVersions(resourceId: string) {
  return getData<Array<{
    resource_id: string
    series_id: string
    version: number
    is_current: boolean
    review_status: string
    adaptation_reason: string
    created_at: string | null
  }>>(`/resources/${resourceId}/versions`)
}

export function exportResource(
  resourceId: string,
  format: 'markdown' | 'pdf',
  audience: 'learner' | 'teacher' = 'learner',
) {
  return postData<{
    resource_version: number
    file_name: string
    file_hash: string
    review_report_id: string | null
    review_status: string
    download_url: string
  }>(`/resources/${resourceId}/export`, { format, audience })
}

export function submitFeedback(
  resourceId: string,
  feedbackType: string,
  rating = 3,
  learnerId = 'learner_001',
) {
  return postData(`/resources/${resourceId}/feedback`, {
    learner_id: learnerId,
    feedback_type: feedbackType,
    rating,
  })
}
