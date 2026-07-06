import { defineStore } from 'pinia'

export const useDomainStore = defineStore('domain', {
  state: () => ({
    currentDomainCode: 'ai_app_dev',
    currentDomainName: '人工智能应用开发实训',
  }),
})
