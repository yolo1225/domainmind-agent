export interface RecoverableTask {
  task_id: string
}

export type ActiveTaskLookup = (learnerId: string) => Promise<RecoverableTask | null>

export async function resolveAgentTaskId(
  explicitTaskId: string,
  learnerId: string,
  loadActiveTask: ActiveTaskLookup,
) {
  const normalizedTaskId = explicitTaskId.trim()
  if (normalizedTaskId) return normalizedTaskId
  const activeTask = await loadActiveTask(learnerId)
  return activeTask?.task_id?.trim() || ''
}
