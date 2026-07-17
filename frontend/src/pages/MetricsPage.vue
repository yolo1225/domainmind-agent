<template>
  <section class="page metrics-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">评测指标</h1>
        <p class="page-subtitle">
          这里展示比赛 MVP 的可复现验收目标，最终数据应由 test_script 离线脚本产出，前端负责清晰呈现。
        </p>
      </div>
      <el-radio-group v-model="mode" @change="loadSummary">
        <el-radio-button value="live">真实运行</el-radio-button>
        <el-radio-button value="baseline">基准数据</el-radio-button>
      </el-radio-group>
    </div>

    <el-alert
      v-if="summary.status === 'not_run'"
      type="warning"
      :closable="false"
      show-icon
      title="尚未生成该模式的评测报告"
    />

    <div v-loading="loading" class="metric-grid">
      <div v-for="metric in metrics" :key="metric.label" class="metric-card">
        <span class="metric-label">{{ metric.label }}</span>
        <div class="metric-value">{{ metric.target }}</div>
        <p>{{ metric.description }}</p>
      </div>
    </div>

    <div class="panel run-summary">
      <div>
        <span class="metric-label">运行状态</span>
        <el-tag :type="summary.status === 'passed' ? 'success' : summary.status === 'failed' ? 'danger' : 'info'">
          {{ statusLabel }}
        </el-tag>
      </div>
      <div>
        <span class="metric-label">案例</span>
        <strong>{{ summary.evaluated_case_count || 0 }}/{{ summary.case_count || 0 }}</strong>
      </div>
      <div>
        <span class="metric-label">任务耗时</span>
        <strong>P50 {{ latency.p50 ?? '-' }} ms / P95 {{ latency.p95 ?? '-' }} ms</strong>
      </div>
      <div>
        <span class="metric-label">运行编号</span>
        <strong>{{ summary.run_id || (mode === 'baseline' ? 'baseline' : '-') }}</strong>
      </div>
    </div>

    <div class="panel">
      <h2 class="panel-title">验收链路</h2>
      <el-table :data="checks" size="large">
        <el-table-column prop="stage" label="阶段" width="170" />
        <el-table-column prop="evidence" label="证明材料" />
        <el-table-column prop="status" label="当前状态" width="160">
          <template #default="{ row }">
            <el-tag :type="row.status === '已接入' ? 'success' : 'warning'" effect="plain">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { getEvaluationSummary, type EvaluationSummary } from '@/api/evaluations'

const mode = ref<'live' | 'baseline'>('live')
const loading = ref(false)
const summary = ref<EvaluationSummary>({
  status: 'not_run',
  run_mode: 'live',
  case_count: 0,
  mvp_target_case_count: 50,
  metrics: {},
})

function percent(value: number | null | undefined) {
  return value == null ? '-' : `${(value * 100).toFixed(1)}%`
}

const metrics = computed(() => [
  { label: '幻觉率', target: percent(summary.value.metrics.hallucination_rate?.ratio), description: '目标 < 5%，按可核验事实计算。' },
  { label: '难度匹配', target: percent(summary.value.metrics.difficulty_match_accuracy?.ratio), description: '目标 >= 85%，匹配画像目标难度。' },
  { label: '核心知识覆盖', target: percent(summary.value.metrics.core_knowledge_coverage?.ratio), description: '目标 >= 90%，覆盖金标准知识点。' },
  { label: '无法判定', target: String(summary.value.unable_to_determine?.count || 0), description: '不进入指标分母，保留案例编号。' },
])

const latency = computed(() => summary.value.metrics.latency_ms || { p50: null, p95: null })
const statusLabel = computed(() => ({ passed: '已通过', failed: '未通过', not_run: '未运行' })[summary.value.status])

const checks = [
  { stage: '诊断画像', evidence: '诊断题、答题记录、profile_id、weak_knowledge', status: '已接入' },
  { stage: '资源生成', evidence: 'generation_task、agent_trace、三类 learning_resource', status: '已接入' },
  { stage: '审核校验', evidence: 'review_report、primary_review、secondary_review、arbitration', status: '已接入' },
  { stage: '反馈更新', evidence: 'feedback、triggered_action、learning_path.needs_refresh', status: '已接入' },
  { stage: '离线评测', evidence: 'baseline 与 live 报告、P50/P95、失败案例', status: '已接入' },
]

async function loadSummary() {
  loading.value = true
  try {
    summary.value = await getEvaluationSummary(mode.value)
  } catch (error) {
    ElMessage.error('评测报告加载失败。')
  } finally {
    loading.value = false
  }
}

onMounted(loadSummary)
</script>

<style scoped>
.metric-card p {
  margin: 8px 0 0;
  color: var(--app-muted);
  font-size: 13px;
  line-height: 1.5;
}

.run-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
}

.run-summary > div {
  display: grid;
  gap: 6px;
}

@media (max-width: 900px) {
  .run-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
