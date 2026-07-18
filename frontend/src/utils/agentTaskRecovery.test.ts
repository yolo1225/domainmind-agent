import { describe, expect, it, vi } from 'vitest'

import { resolveAgentTaskId } from './agentTaskRecovery'

describe('Agent task recovery', () => {
  it('prefers an explicit task id without querying active tasks', async () => {
    const lookup = vi.fn()

    await expect(resolveAgentTaskId(' task_explicit ', 'learner_001', lookup)).resolves.toBe(
      'task_explicit',
    )
    expect(lookup).not.toHaveBeenCalled()
  })

  it('recovers the active task for the selected learner', async () => {
    const lookup = vi.fn().mockResolvedValue({ task_id: 'task_active' })

    await expect(resolveAgentTaskId('', 'learner_002', lookup)).resolves.toBe('task_active')
    expect(lookup).toHaveBeenCalledWith('learner_002')
  })

  it('returns an empty id when the learner has no active task', async () => {
    const lookup = vi.fn().mockResolvedValue(null)

    await expect(resolveAgentTaskId('', 'learner_001', lookup)).resolves.toBe('')
  })

  it('propagates active-task lookup failures to the page error state', async () => {
    const lookup = vi.fn().mockRejectedValue(new Error('network unavailable'))

    await expect(resolveAgentTaskId('', 'learner_001', lookup)).rejects.toThrow(
      'network unavailable',
    )
  })
})
