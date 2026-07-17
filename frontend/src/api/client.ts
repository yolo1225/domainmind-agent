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

export async function patchData<T>(url: string, body: unknown): Promise<T> {
  const response = await apiClient.patch<ApiResponse<T>>(url, body)
  return response.data.data
}

export function subscribeTaskEvents(
  taskId: string,
  onEvent: (event: AgentStatusEvent) => void,
): EventSource {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || fallbackBaseUrl
  const source = new EventSource(`${baseUrl}/generation-tasks/${taskId}/events`)
  const eventTypes = [
    'trigger_routed',
    'agent_status',
    'feedback_classified',
    'profile_update_decided',
    'profile_updated',
    'profile_unchanged',
    'review_disagreement',
    'review_retrieval_started',
    'manual_review_required',
    'manual_review_resolved',
    'path_refresh_started',
    'path_refresh_completed',
    'resource_created',
    'task_completed',
    'task_failed',
  ] as const
  eventTypes.forEach((eventType) => {
    source.addEventListener(eventType, (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as AgentStatusEvent
      onEvent({ ...payload, event_type: eventType })
    })
  })
  return source
}
