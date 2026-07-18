import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getData } from './client'
import { getActiveGenerationTask } from './generation'

vi.mock('./client', () => ({
  getData: vi.fn(),
  postData: vi.fn(),
}))

describe('generation task API', () => {
  beforeEach(() => {
    vi.mocked(getData).mockReset()
  })

  it('queries the active task for the encoded learner id', async () => {
    vi.mocked(getData).mockResolvedValue(null)

    await getActiveGenerationTask('learner demo/1')

    expect(getData).toHaveBeenCalledWith(
      '/generation-tasks/active?learner_id=learner%20demo%2F1',
    )
  })
})
