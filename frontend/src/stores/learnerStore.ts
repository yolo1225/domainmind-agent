import { defineStore } from 'pinia'

const STORAGE_KEY = 'domainmind:selectedLearnerId'
const DEFAULT_LEARNER_ID = 'learner_001'

function readStoredLearnerId() {
  if (typeof window === 'undefined') return DEFAULT_LEARNER_ID
  return window.localStorage.getItem(STORAGE_KEY) || DEFAULT_LEARNER_ID
}

export const useLearnerStore = defineStore('learner', {
  state: () => ({
    selectedLearnerId: readStoredLearnerId(),
  }),
  actions: {
    setSelectedLearner(learnerId: string) {
      const nextLearnerId = learnerId.trim() || DEFAULT_LEARNER_ID
      this.selectedLearnerId = nextLearnerId
      window.localStorage.setItem(STORAGE_KEY, nextLearnerId)
    },
  },
})
