import axios from 'axios'

import type { AgentStatusEvent, ApiResponse } from '@/types/api'

const fallbackBaseUrl = '/api/v1'

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || fallbackBaseUrl,
  timeout: 15000,
})

export async function getData<T>(url: string): Promise<T> {
  const response = await apiClient.get<ApiResponse<T>>(url)
  return response.data.data
}

export async function postData<T>(url: string, body?: unknown): Promise<T> {
  const response = await apiClient.post<ApiResponse<T>>(url, body ?? {})
  return response.data.data
}

export function subscribeTaskEvents(
  taskId: string,
  onEvent: (event: AgentStatusEvent) => void,
): EventSource {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || fallbackBaseUrl
  const source = new EventSource(`${baseUrl}/generation-tasks/${taskId}/events`)
  source.addEventListener('agent_status', (event) => {
    onEvent(JSON.parse((event as MessageEvent).data))
  })
  source.addEventListener('task_status', (event) => {
    onEvent(JSON.parse((event as MessageEvent).data))
  })
  return source
}
