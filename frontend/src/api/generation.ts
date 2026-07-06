import { getData, postData } from './client'

export interface GenerationTaskResult {
  task_id: string
  status: string
  resource_types: string[]
  agent_graph: string
  decision: string
  agent_trace: Array<{
    agent_name: string
    status: string
    output: Record<string, unknown>
  }>
  resources: Array<{
    resource_id: string
    resource_type: string
    title: string
    difficulty: number
    review_status: string
    sources: string[]
  }>
}

export function createGenerationTask(profileId?: string) {
  return postData<GenerationTaskResult>('/generation-tasks', {
    learner_id: 'learner_001',
    profile_id: profileId,
    domain_code: 'ai_app_dev',
    resource_types: ['lecture', 'practice_guide', 'graded_quiz'],
  })
}

export function getGenerationTask(taskId: string) {
  return getData<{ task_id: string; status: string; decision: string }>(`/generation-tasks/${taskId}`)
}
