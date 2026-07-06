import { defineStore } from 'pinia'

export const useTaskStore = defineStore('task', {
  state: () => ({
    currentTaskId: '',
    events: [] as Array<{ step: string; status: string }>,
  }),
  actions: {
    setTask(taskId: string) {
      this.currentTaskId = taskId
      this.events = []
    },
    addEvent(step: string, status: string) {
      this.events.push({ step, status })
    },
  },
})
