import { getData, postData } from './client'

export interface GenerationTaskResult {
  task_id: string
  thread_id: string
  learner_id?: string | null
  profile_id?: string | null
  profile_version?: number | null
  profile_source?: string | null
  profile_changed_dimensions?: string[]
  status: string
  trigger_type: string
  execution_mode: string
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

export interface GenerationTaskDetail {
  task_id: string
  thread_id?: string
  learner_id?: string | null
  profile_id?: string | null
  profile_version?: number | null
  profile_source?: string | null
  profile_changed_dimensions?: string[]
  status: string
  progress?: number
  trigger_type?: string
  execution_mode?: string
  revision_count: number
  decision: string
  resources: GenerationTaskResult['resources']
}

export function createGenerationTask(
  profileId?: string,
  learnerId = 'learner_001',
  learningGoal = '个性化学习资源生成',
) {
  return postData<GenerationTaskResult>('/generation-tasks', {
    learner_id: learnerId,
    profile_id: profileId,
    domain_code: 'ai_app_dev',
    trigger_type: 'initial_generation',
    execution_mode: 'auto',
    learning_goal: learningGoal,
    resource_types: ['lecture', 'practice_guide', 'graded_quiz'],
  })
}

export function getAgentRuns(taskId: string) {
  return getData<Array<Record<string, unknown>>>(`/generation-tasks/${taskId}/agent-runs`)
}

export function getGenerationTask(taskId: string) {
  return getData<GenerationTaskDetail>(`/generation-tasks/${taskId}`)
}

export function getActiveGenerationTask(learnerId = 'learner_001') {
  return getData<GenerationTaskDetail | null>(
    `/generation-tasks/active?learner_id=${encodeURIComponent(learnerId)}`,
  )
}
