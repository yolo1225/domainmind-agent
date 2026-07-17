import { getData } from './client'

export interface LearningReport {
  learner_id: string
  profile_id?: string | null
  profile_type?: string
  radar: number[]
  path: string[]
  diagnostic_summary?: {
    answer_count: number
    correct_count: number
    accuracy: number
    latest_session_id?: string | null
  }
  path_detail?: Array<{
    name: string
    description?: string
  }>
  weak_knowledge?: Array<{
    knowledge_id: string
    name: string
    category: string
    weakness_level: number
  }>
  metrics: {
    hallucination_rate: number
    difficulty_match: number
    difficulty_match_accuracy?: number
    knowledge_coverage: number
  }
  loop_status: {
    diagnosis: string
    profile: string
    generation: string
    review: string
    feedback: string
    path_update: string
  }
  resource_summary: {
    total: number
    by_type: Record<string, number>
    recent: Array<{
      resource_id: string
      resource_type: string
      resource_type_label: string
      title: string
      difficulty: number
      review_status: string
      source_count: number
      generation_task_id?: string | null
      generation_status?: string | null
      generation_decision?: string | null
      generated_at?: string | null
    }>
  }
  review_summary: {
    total_reports: number
    passed: number
    manual_review_required: number
    review_status_counts: Record<string, number>
    source_coverage: number
  }
  feedback_summary: {
    total: number
    latest_action?: string | null
    learning_path_needs_refresh: boolean
    path_refresh_performed?: boolean
    recent: Array<{
      resource_id: string
      resource_title: string
      feedback_type: string
      rating: number
      triggered_action: string
      created_at?: string | null
    }>
  }
  next_actions: Array<{
    type: string
    label: string
    description: string
    route: string
  }>
}

export function getLearningReport(learnerId: string) {
  return getData<LearningReport>(`/reports/learners/${learnerId}`)
}
