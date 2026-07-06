import { getData } from './client'

export interface LearnerSummary {
  learner_id: string
  profile_type: string
  target_domain: string
  ability_level: number
}

export function listLearners() {
  return getData<LearnerSummary[]>('/learners')
}
