import { defineStore } from 'pinia'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    userId: 'demo_admin',
    role: 'admin',
  }),
})
