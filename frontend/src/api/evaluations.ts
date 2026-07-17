import { getData } from './client'

export interface RatioMetric {
  numerator: number
  denominator: number
  ratio: number | null
}

export interface EvaluationSummary {
  status: 'passed' | 'failed' | 'not_run'
  run_mode: 'live' | 'baseline'
  run_id?: string | null
  stage?: string | null
  case_count: number
  evaluated_case_count?: number
  mvp_target_case_count: number
  evaluated_at?: string | null
  model_configuration?: Record<string, string | boolean | null>
  metrics: {
    hallucination_rate?: RatioMetric
    difficulty_match_accuracy?: RatioMetric
    core_knowledge_coverage?: RatioMetric
    review_decision_accuracy?: RatioMetric
    profile_decision_accuracy?: RatioMetric
    latency_ms?: { p50: number | null; p95: number | null }
    agent_latency_ms?: Record<string, { p50: number | null; p95: number | null }>
  }
  unable_to_determine?: { count: number; case_ids: string[]; statement: string }
}

export function getEvaluationSummary(mode: 'live' | 'baseline' = 'live') {
  return getData<EvaluationSummary>(`/evaluations/summary?mode=${mode}`)
}
