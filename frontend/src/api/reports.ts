import { getData } from './client'

export interface LearningReport {
  learner_id: string
  profile_id?: string | null
  profile_type?: string
  radar: number[]
  path: string[]
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
}

export function getLearningReport(learnerId: string) {
  return getData<LearningReport>(`/reports/learners/${learnerId}`)
}
