import { defineStore } from 'pinia'

import type { AgentStatusEvent } from '@/types/api'

function latestPayloadValue(
  events: AgentStatusEvent[],
  key: string,
): string | number | boolean | null {
  for (const event of [...events].reverse()) {
    const value = event.payload?.[key]
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      return value
    }
  }
  return null
}

function eventKey(event: AgentStatusEvent) {
  if (event.run_id) {
    return `${event.task_id}:run:${event.run_id}:${event.status}`
  }
  return [
    event.task_id,
    event.step,
    event.status,
    event.decision ?? '',
    event.generation_round ?? '',
    event.timestamp ?? '',
  ].join(':')
}

export const useTaskStore = defineStore('task', {
  state: () => ({
    currentTaskId: '',
    events: [] as AgentStatusEvent[],
  }),
  getters: {
    latestEvent: (state) => state.events[state.events.length - 1],
    currentRound: (state) => {
      const rounds = state.events
        .map((event) => event.generation_round)
        .filter((round): round is number => typeof round === 'number')
      return rounds.length ? Math.max(...rounds) : 0
    },
    latestDecision: (state) => {
      const taskEvent = [...state.events].reverse().find((event) => event.decision)
      const decisionValue = latestPayloadValue(state.events, 'decision')
      return taskEvent?.decision ?? (typeof decisionValue === 'string' ? decisionValue : 'pending')
    },
    latestStrategy: (state) => {
      const value = latestPayloadValue(state.events, 'strategy')
      return typeof value === 'string' ? value : 'pending'
    },
    latestDifficulty: (state) => {
      const value = latestPayloadValue(state.events, 'target_difficulty')
      if (typeof value === 'number') return value
      const fallback = latestPayloadValue(state.events, 'difficulty')
      return typeof fallback === 'number' ? fallback : null
    },
    latestAverageScore: (state) => {
      const value = latestPayloadValue(state.events, 'average_score')
      return typeof value === 'number' ? value : null
    },
    latestRevisionTypes: (state) => {
      const event = [...state.events]
        .reverse()
        .find((item) => Array.isArray(item.payload?.revision_resource_types))
      return (event?.payload?.revision_resource_types as string[] | undefined) ?? []
    },
    latestMissingRequirements: (state) => {
      const event = [...state.events]
        .reverse()
        .find((item) => Array.isArray(item.payload?.missing_requirements))
      return (event?.payload?.missing_requirements as string[] | undefined) ?? []
    },
    latestPreservedResourceCount: (state) => {
      const value = latestPayloadValue(state.events, 'preserved_resource_count')
      return typeof value === 'number' ? value : 0
    },
  },
  actions: {
    clearTask() {
      this.currentTaskId = ''
      this.events = []
    },
    setTask(taskId: string) {
      this.currentTaskId = taskId
      this.events = []
    },
    addEvent(eventOrStep: AgentStatusEvent | string, status?: string) {
      if (typeof eventOrStep === 'string') {
        const event = {
          task_id: this.currentTaskId,
          step: eventOrStep,
          status: status ?? 'pending',
        }
        if (!this.events.some((item) => eventKey(item) === eventKey(event))) {
          this.events.push(event)
        }
        return
      }
      if (this.events.some((item) => eventKey(item) === eventKey(eventOrStep))) {
        return
      }
      this.events.push(eventOrStep)
    },
  },
})
