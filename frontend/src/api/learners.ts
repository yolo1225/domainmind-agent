import { getData, postData } from './client'

export interface LearnerSummary {
  learner_id: string
  profile_type: string
  target_domain: string
  ability_level: number
  profile_status: 'ready' | 'not_started'
  latest_profile_id?: string | null
  updated_at?: string | null
}

export interface WeakKnowledge {
  knowledge_id: string
  name: string
  category: string
  weakness_level: number
  weakness_type?: string
  suggested_action?: string
  evidence?: {
    wrong_count: number
    attempts: number
    avg_score: number
  }
  prerequisites?: string[]
}

export interface LearningPathStage {
  name: string
  description?: string
  knowledge_ids?: string[]
  resource_types?: string[]
  trigger?: string
}

export interface LearnerProfileDetail {
  learner_id: string
  domain_code: string
  background: string
  learning_style: string
  experience_years: number
  profile_status: 'ready' | 'not_started'
  profile_id: string | null
  profile_type: string
  ability_profile: Record<string, unknown>
  radar: number[]
  category_mastery: Record<string, number>
  weak_knowledge: WeakKnowledge[]
  learning_path: {
    profile_type?: string
    score?: number
    stages?: LearningPathStage[]
    needs_refresh?: boolean
  } | null
  diagnostic_summary: {
    answer_count: number
    correct_count: number
    accuracy: number
    latest_session_id?: string | null
  }
}

export interface LearnerCreatePayload {
  learner_id: string
  background: string
  target_domain: string
  experience_years: number
  learning_style: 'theory' | 'practice' | 'mixed'
}

export function listLearners() {
  return getData<LearnerSummary[]>('/learners')
}

export function createLearner(payload: LearnerCreatePayload) {
  return postData<LearnerSummary>('/learners', payload)
}

export function getLearnerProfile(learnerId: string) {
  return getData<LearnerProfileDetail>(`/learners/${learnerId}/profile`)
}
