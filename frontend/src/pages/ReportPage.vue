<template>
  <section class="page report-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">学习报告</h1>
        <p class="page-subtitle">
          汇总当前学习者从诊断画像、资源生成、审核校验到反馈更新的闭环结果。
        </p>
      </div>
      <div class="toolbar">
        <el-tag effect="plain">{{ learnerStore.selectedLearnerId }}</el-tag>
        <el-button :loading="loading" @click="load">刷新报告</el-button>
      </div>
    </div>

    <div v-if="loading" class="panel">
      <el-skeleton :rows="8" animated />
    </div>

    <el-alert
      v-else-if="errorMessage"
      class="panel"
      type="error"
      show-icon
      :title="errorMessage"
    />

    <template v-else-if="report">
      <section class="panel loop-panel">
        <div class="section-head">
          <div>
            <h2 class="panel-title">闭环状态</h2>
            <p class="panel-caption">按比赛演示链路查看每个环节是否已经产生可展示结果。</p>
          </div>
          <el-tag :type="report.feedback_summary.learning_path_needs_refresh ? 'warning' : 'success'">
            {{ report.feedback_summary.learning_path_needs_refresh ? '路径待刷新' : '路径当前有效' }}
          </el-tag>
        </div>
        <div class="loop-steps">
          <div
            v-for="step in loopSteps"
            :key="step.key"
            class="loop-step"
            :class="{ 'is-complete': step.complete, 'needs-refresh': step.needsRefresh }"
          >
            <span class="status-dot" :class="{ 'is-done': step.complete, 'is-active': step.needsRefresh }" />
            <div>
              <strong>{{ step.label }}</strong>
              <small>{{ step.description }}</small>
            </div>
          </div>
        </div>
      </section>

      <section class="metric-grid">
        <div class="metric-card">
          <span class="metric-label">生成资源</span>
          <strong class="metric-value">{{ report.resource_summary.total }}</strong>
        </div>
        <div class="metric-card">
          <span class="metric-label">审核通过</span>
          <strong class="metric-value">
            {{ report.review_summary.passed }}/{{ report.review_summary.total_reports }}
          </strong>
        </div>
        <div class="metric-card">
          <span class="metric-label">反馈触发</span>
          <strong class="metric-value">{{ report.feedback_summary.total }}</strong>
        </div>
        <div class="metric-card">
          <span class="metric-label">知识来源覆盖</span>
          <strong class="metric-value">{{ report.review_summary.source_coverage }}</strong>
        </div>
      </section>

      <div class="report-layout">
        <main class="report-main">
          <section class="panel">
            <div class="section-head">
              <div>
                <h2 class="panel-title">生成资源清单</h2>
                <p class="panel-caption">按最近生成结果展示资源类型、审核状态和来源数量。</p>
              </div>
              <div class="type-tags">
                <el-tag effect="plain">讲义 {{ resourceCount('lecture') }}</el-tag>
                <el-tag effect="plain">实训 {{ resourceCount('practice_guide') }}</el-tag>
                <el-tag effect="plain">测验 {{ resourceCount('graded_quiz') }}</el-tag>
              </div>
            </div>
            <el-table v-if="report.resource_summary.recent.length" :data="report.resource_summary.recent">
              <el-table-column prop="title" label="资源" min-width="180" />
              <el-table-column label="类型" width="110">
                <template #default="{ row }">{{ row.resource_type_label }}</template>
              </el-table-column>
              <el-table-column label="难度" width="80">
                <template #default="{ row }">{{ row.difficulty }}</template>
              </el-table-column>
              <el-table-column label="审核" width="120">
                <template #default="{ row }">
                  <el-tag :type="row.review_status === 'passed' ? 'success' : 'warning'" effect="plain">
                    {{ reviewLabel(row.review_status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="来源" width="90">
                <template #default="{ row }">{{ row.source_count }}</template>
              </el-table-column>
            </el-table>
            <div v-else class="empty-hint small">
              <strong>还没有生成学习资源</strong>
              <p>先在学情画像页生成个性化资源，报告页会自动汇总三类资源与审核结果。</p>
              <el-button type="primary" @click="router.push('/learners')">去生成资源</el-button>
            </div>
          </section>

          <section class="panel">
            <div class="section-head">
              <div>
                <h2 class="panel-title">审核与溯源</h2>
                <p class="panel-caption">展示资源审核分布，以及是否存在需要人工复核的内容。</p>
              </div>
              <el-tag
                :type="report.review_summary.manual_review_required > 0 ? 'danger' : 'success'"
                effect="plain"
              >
                人工复核 {{ report.review_summary.manual_review_required }}
              </el-tag>
            </div>
            <div class="review-grid">
              <div v-for="item in reviewRows" :key="item.status" class="review-item">
                <span>{{ item.label }}</span>
                <strong>{{ item.count }}</strong>
              </div>
            </div>
            <div class="quality-list">
              <div>
                <span>幻觉率</span>
                <strong>{{ percent(report.metrics.hallucination_rate) }}</strong>
              </div>
              <div>
                <span>难度匹配</span>
                <strong>{{ percent(report.metrics.difficulty_match_accuracy ?? report.metrics.difficulty_match) }}</strong>
              </div>
              <div>
                <span>知识覆盖</span>
                <strong>{{ percent(report.metrics.knowledge_coverage) }}</strong>
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="section-head">
              <div>
                <h2 class="panel-title">反馈触发与路径更新</h2>
                <p class="panel-caption">学习者反馈会触发辅导动作，并标记学习路径是否需要刷新。</p>
              </div>
              <el-tag :type="report.feedback_summary.total ? 'success' : 'info'" effect="plain">
                {{ report.feedback_summary.total }} 条反馈
              </el-tag>
            </div>
            <div v-if="report.feedback_summary.recent.length" class="feedback-list">
              <div v-for="item in report.feedback_summary.recent" :key="`${item.resource_id}-${item.created_at}`">
                <div>
                  <strong>{{ item.resource_title }}</strong>
                  <small>{{ formatDateTime(item.created_at) }}</small>
                </div>
                <el-tag effect="plain">{{ feedbackLabel(item.feedback_type) }}</el-tag>
                <el-tag type="warning" effect="plain">{{ actionLabel(item.triggered_action) }}</el-tag>
              </div>
            </div>
            <div v-else class="empty-hint small">
              <strong>还没有提交学习反馈</strong>
              <p>到学习资源页对某个资源提交“太难、太简单、看不懂或有错误”，这里会显示触发结果。</p>
              <el-button @click="router.push('/resources')">去提交反馈</el-button>
            </div>
          </section>
        </main>

        <aside class="report-side">
          <section class="panel profile-brief">
            <h2 class="panel-title">画像摘要</h2>
            <div class="profile-row">
              <span>画像</span>
              <strong>{{ report.profile_id || '待生成' }}</strong>
            </div>
            <div class="profile-row">
              <span>类型</span>
              <strong>{{ profileLabel(report.profile_type || 'not_started') }}</strong>
            </div>
            <div class="profile-row">
              <span>诊断正确率</span>
              <strong>{{ report.diagnostic_summary?.accuracy ?? 0 }}%</strong>
            </div>
            <div class="radar-mini">
              <span v-for="item in radarRows" :key="item.label">
                <b>{{ item.label }}</b>
                <i>{{ item.value }}</i>
              </span>
            </div>
          </section>

          <section class="panel">
            <h2 class="panel-title">下一步建议</h2>
            <div class="next-actions">
              <button
                v-for="action in report.next_actions"
                :key="action.type"
                class="next-action"
                type="button"
                @click="router.push(action.route)"
              >
                <strong>{{ action.label }}</strong>
                <span>{{ action.description }}</span>
              </button>
            </div>
          </section>
        </aside>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { getLearningReport, type LearningReport } from '@/api/reports'
import { useLearnerStore } from '@/stores/learnerStore'

const router = useRouter()
const learnerStore = useLearnerStore()
const report = ref<LearningReport | null>(null)
const loading = ref(false)
const errorMessage = ref('')

function normalizeReport(raw: LearningReport): LearningReport {
  return {
    ...raw,
    diagnostic_summary: raw.diagnostic_summary ?? {
      answer_count: 0,
      correct_count: 0,
      accuracy: 0,
      latest_session_id: null,
    },
    loop_status: raw.loop_status ?? {
      diagnosis: (raw.diagnostic_summary?.answer_count ?? 0) > 0 ? 'completed' : 'pending',
      profile: raw.profile_id ? 'completed' : 'pending',
      generation: 'pending',
      review: 'pending',
      feedback: 'pending',
      path_update: 'current',
    },
    resource_summary: raw.resource_summary ?? {
      total: 0,
      by_type: { lecture: 0, practice_guide: 0, graded_quiz: 0 },
      recent: [],
    },
    review_summary: raw.review_summary ?? {
      total_reports: 0,
      passed: 0,
      manual_review_required: 0,
      review_status_counts: {},
      source_coverage: 0,
    },
    feedback_summary: raw.feedback_summary ?? {
      total: 0,
      latest_action: null,
      learning_path_needs_refresh: false,
      recent: [],
    },
    next_actions: raw.next_actions ?? [
      {
        type: 'generation',
        label: '生成个性化资源',
        description: '基于当前画像生成讲义、实训指导和分级测验。',
        route: '/learners',
      },
    ],
  }
}

const loopSteps = computed(() => {
  const status = report.value?.loop_status
  return [
    {
      key: 'diagnosis',
      label: '诊断',
      description: status?.diagnosis === 'completed' ? '已有答题记录' : '等待测评',
      complete: status?.diagnosis === 'completed',
    },
    {
      key: 'profile',
      label: '画像',
      description: status?.profile === 'completed' ? '画像已生成' : '等待画像',
      complete: status?.profile === 'completed',
    },
    {
      key: 'generation',
      label: '生成',
      description: status?.generation === 'completed' ? '资源已入库' : '等待生成',
      complete: status?.generation === 'completed',
    },
    {
      key: 'review',
      label: '审核',
      description: status?.review === 'completed' ? '已有审核结果' : '等待审核',
      complete: status?.review === 'completed',
    },
    {
      key: 'feedback',
      label: '反馈',
      description: status?.feedback === 'completed' ? '已触发辅导动作' : '等待反馈',
      complete: status?.feedback === 'completed',
    },
    {
      key: 'path_update',
      label: '更新',
      description: status?.path_update === 'needs_refresh' ? '路径需要刷新' : '路径当前有效',
      complete: status?.path_update === 'current',
      needsRefresh: status?.path_update === 'needs_refresh',
    },
  ]
})

const reviewRows = computed(() => {
  const counts = report.value?.review_summary.review_status_counts ?? {}
  const statuses = Object.keys(counts)
  const rows = statuses.length
    ? statuses.map((status) => ({ status, label: reviewLabel(status), count: counts[status] }))
    : [{ status: 'pending', label: '暂无审核', count: 0 }]
  return rows
})

const radarRows = computed(() => {
  const values = report.value?.radar ?? [0, 0, 0, 0, 0]
  return [
    { label: '理论', value: values[0] ?? 0 },
    { label: '实操', value: values[1] ?? 0 },
    { label: '问题解决', value: values[2] ?? 0 },
    { label: '广度', value: values[3] ?? 0 },
    { label: '速度', value: values[4] ?? 0 },
  ]
})

function resourceCount(type: string) {
  return report.value?.resource_summary.by_type[type] ?? 0
}

function percent(value: number) {
  if (value <= 1) return `${Math.round(value * 100)}%`
  return `${Math.round(value)}%`
}

function profileLabel(profileType: string) {
  return (
    {
      beginner: '基础补齐型',
      intermediate: '能力提升型',
      advanced: '挑战拓展型',
      practice_oriented: '实操优势型',
      not_started: '待诊断',
    }[profileType] ?? profileType
  )
}

function reviewLabel(status: string) {
  return (
    {
      passed: '审核通过',
      failed: '审核未通过',
      revision_required: '需要修订',
      pending: '等待审核',
    }[status] ?? status
  )
}

function feedbackLabel(type: string) {
  return (
    {
      too_easy: '太简单',
      too_hard: '太难',
      incorrect: '有错误',
      confusing: '看不懂',
    }[type] ?? type
  )
}

function actionLabel(action: string) {
  return (
    {
      challenge_task: '挑战任务',
      remedial_explanation: '补救解释',
      revision_required: '资源修订',
      profile_update: '画像更新',
    }[action] ?? action
  )
}

function formatDateTime(value?: string | null) {
  if (!value) return '时间未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    report.value = normalizeReport(await getLearningReport(learnerStore.selectedLearnerId))
  } catch (error) {
    report.value = null
    errorMessage.value = '学习报告加载失败，请确认后端服务可用，或先创建对应学习者。'
    ElMessage.error(errorMessage.value)
  } finally {
    loading.value = false
  }
}

watch(
  () => learnerStore.selectedLearnerId,
  () => load(),
)

onMounted(load)
</script>

<style scoped>
.report-page {
  gap: 18px;
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.panel-caption {
  margin: -6px 0 0;
  color: var(--app-muted);
  font-size: 13px;
  line-height: 1.6;
}

.loop-panel {
  display: grid;
  gap: 12px;
}

.loop-steps {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}

.loop-step {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  min-width: 0;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-panel-soft);
  padding: 12px;
}

.loop-step.is-complete {
  border-color: rgb(22 163 74 / 0.28);
  background: rgb(22 163 74 / 0.07);
}

.loop-step.needs-refresh {
  border-color: rgb(217 119 6 / 0.28);
  background: rgb(217 119 6 / 0.08);
}

.loop-step strong,
.loop-step small {
  display: block;
}

.loop-step small {
  margin-top: 4px;
  color: var(--app-muted);
  font-size: 12px;
  line-height: 1.45;
}

.report-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
  align-items: start;
}

.report-main,
.report-side {
  display: grid;
  gap: 16px;
}

.type-tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.empty-hint.small {
  padding: 16px;
}

.empty-hint p {
  margin: 8px 0 14px;
  color: var(--app-muted);
  line-height: 1.7;
}

.review-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.review-item,
.profile-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-panel-soft);
  padding: 12px;
}

.review-item span,
.profile-row span {
  color: var(--app-muted);
}

.quality-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.quality-list div {
  display: grid;
  gap: 7px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  padding: 12px;
}

.quality-list span {
  color: var(--app-muted);
  font-size: 13px;
}

.quality-list strong {
  font-size: 22px;
}

.feedback-list {
  display: grid;
  gap: 10px;
}

.feedback-list > div {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  padding: 12px;
}

.feedback-list strong,
.feedback-list small {
  display: block;
}

.feedback-list small {
  margin-top: 4px;
  color: var(--app-muted);
}

.profile-brief {
  display: grid;
  gap: 10px;
}

.profile-row strong {
  min-width: 0;
  overflow: hidden;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.radar-mini {
  display: grid;
  gap: 8px;
  margin-top: 2px;
}

.radar-mini span {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) 36px;
  align-items: center;
  gap: 8px;
  color: var(--app-muted);
  font-size: 13px;
}

.radar-mini span::before {
  content: "";
  order: 2;
  height: 7px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--app-accent), var(--app-info));
  opacity: 0.72;
}

.radar-mini b {
  font-weight: 600;
}

.radar-mini i {
  order: 3;
  color: var(--app-text);
  font-style: normal;
  font-weight: 700;
  text-align: right;
}

.next-actions {
  display: grid;
  gap: 10px;
}

.next-action {
  display: grid;
  gap: 5px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-panel-soft);
  padding: 12px;
  color: var(--app-text);
  text-align: left;
  cursor: pointer;
}

.next-action:hover {
  border-color: #93b4ef;
  background: var(--app-accent-soft);
}

.next-action span {
  color: var(--app-muted);
  font-size: 13px;
  line-height: 1.6;
}

@media (max-width: 1180px) {
  .loop-steps {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .report-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .section-head,
  .feedback-list > div {
    display: grid;
  }

  .loop-steps,
  .quality-list {
    grid-template-columns: 1fr;
  }

  .type-tags {
    justify-content: flex-start;
  }
}
</style>
