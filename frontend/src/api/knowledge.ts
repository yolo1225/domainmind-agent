import { getData, postData } from '@/api/client'

export interface KnowledgeItem {
  knowledge_id: string
  domain_code: string
  name: string
  category: string
  difficulty: number
  tags: string[]
  content: string
  source_title: string
  source_url: string | null
  license_note: string
  needs_reembedding: boolean
}

export interface KnowledgeItemsResponse {
  domain_code: string
  items: KnowledgeItem[]
  total: number
  limit: number
  offset: number
  mvp_target: number
}

export interface KnowledgeSearchMatch {
  id: string
  knowledge_id: string
  name: string
  category: string
  difficulty: number
  source_title: string
  distance: number
  preview: string
}

export interface KnowledgeSearchResponse {
  domain_code: string
  query: string
  matches: KnowledgeSearchMatch[]
  total: number
  embedding_model: string
}

export interface KnowledgeItemCreateRequest {
  domain_code: string
  name: string
  category: string
  difficulty: number
  tags: string[]
  content: string
  source_title: string
  source_url?: string | null
  license_note: string
}

export interface KnowledgeItemCreateResponse {
  item: KnowledgeItem
  index_status: string
  affected_learning_paths: number
  next_action: string
}

export function listKnowledgeItems(domainCode = 'ai_app_dev', limit = 100) {
  const params = new URLSearchParams({
    domain_code: domainCode,
    limit: String(limit),
  })
  return getData<KnowledgeItemsResponse>(`/knowledge/items?${params.toString()}`)
}

export function searchKnowledge(query: string, domainCode = 'ai_app_dev', nResults = 5) {
  const params = new URLSearchParams({
    query,
    domain_code: domainCode,
    n_results: String(nResults),
  })
  return getData<KnowledgeSearchResponse>(`/knowledge/search?${params.toString()}`)
}

export function createKnowledgeItem(payload: KnowledgeItemCreateRequest) {
  return postData<KnowledgeItemCreateResponse>('/knowledge/items', payload)
}

export function rebuildKnowledgeIndex() {
  return postData<{ status: string; affected_domain: string }>('/knowledge/rebuild-index')
}
