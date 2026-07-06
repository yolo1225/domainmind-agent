import { getData } from './client'

export interface LearningReport {
  learner_id: string
  radar: number[]
  path: string[]
  metrics: {
    hallucination_rate: number
    difficulty_match: number
    knowledge_coverage: number
  }
}

export function getLearningReport(learnerId: string) {
  return getData<LearningReport>(`/reports/learners/${learnerId}`)
}
