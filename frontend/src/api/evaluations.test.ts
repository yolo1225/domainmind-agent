import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getData } from './client'
import { getEvaluationSummary } from './evaluations'

vi.mock('./client', () => ({
  getData: vi.fn(),
}))

describe('evaluation API', () => {
  beforeEach(() => {
    vi.mocked(getData).mockReset()
  })

  it('loads live results by default', async () => {
    vi.mocked(getData).mockResolvedValue({ status: 'not_run' })

    await getEvaluationSummary()

    expect(getData).toHaveBeenCalledWith('/evaluations/summary?mode=live')
  })

  it('can request the reproducible baseline explicitly', async () => {
    vi.mocked(getData).mockResolvedValue({ status: 'passed' })

    await getEvaluationSummary('baseline')

    expect(getData).toHaveBeenCalledWith('/evaluations/summary?mode=baseline')
  })
})
