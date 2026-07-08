<template>
  <section class="page resource-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">学习资源</h1>
        <p class="page-subtitle">
          按生成批次查看讲义、实训指导和分级测验。带有任务编号的入口会自动定位到本次生成结果。
        </p>
      </div>
      <div class="toolbar">
        <el-button :loading="loading" @click="load">刷新资源</el-button>
        <el-button type="primary" @click="router.push('/diagnostics')">生成新资源</el-button>
      </div>
    </div>

    <div v-if="loading" class="panel loading-panel">
      <el-skeleton :rows="5" animated />
    </div>

    <div v-else-if="requestedTaskId && !selectedBatch" class="empty-hint">
      <strong>没有找到这次生成的资源</strong>
      <p>任务可能仍在生成，刷新资源或前往 Agent 协同页查看进度。</p>
      <div class="empty-actions">
        <el-button :loading="loading" @click="load">刷新资源</el-button>
        <el-button @click="router.push('/agents')">查看 Agent 进度</el-button>
      </div>
    </div>

    <div v-else-if="!resources.length" class="empty-hint">
      <strong>还没有学习资源</strong>
      <p>请先完成诊断测评，或在 Agent 协同页启动一次生成流程。</p>
    </div>

    <div v-else class="resource-layout">
      <aside class="panel batch-list">
        <div class="section-head">
          <h2 class="panel-title">生成批次</h2>
          <el-tag effect="plain">{{ batches.length }} 批</el-tag>
        </div>
        <button
          v-for="batch in batches"
          :key="batch.taskId"
          class="batch-tab"
          :class="{ 'is-active': selectedBatch?.taskId === batch.taskId }"
          type="button"
          @click="selectBatch(batch.taskId)"
        >
          <span class="batch-topline">
            <el-tag
              size="small"
              :type="isRequestedBatch(batch.taskId) ? 'success' : 'info'"
              effect="plain"
            >
              {{ isRequestedBatch(batch.taskId) ? '本次生成' : '历史生成' }}
            </el-tag>
            <small>{{ formatDateTime(batch.taskCreatedAt) }}</small>
          </span>
          <strong>{{ batch.taskId }}</strong>
          <span class="batch-meta">
            {{ batch.resources.length }} 类资源 · {{ decisionLabel(batch.decision) }}
          </span>
          <span class="batch-meta">
            画像 {{ batch.profileType || '未标注' }} · 难度 {{ batch.targetDifficulty || '-' }}
          </span>
        </button>
      </aside>

      <main v-if="selectedBatch" class="resource-main">
        <div class="panel batch-summary">
          <div>
            <div class="summary-kicker">
              <el-tag :type="isRequestedBatch(selectedBatch.taskId) ? 'success' : 'info'" effect="plain">
                {{ isRequestedBatch(selectedBatch.taskId) ? '本次生成' : '当前批次' }}
              </el-tag>
              <span>{{ selectedBatch.taskId }}</span>
            </div>
            <h2>生成结果</h2>
            <p class="muted">
              {{ formatDateTime(selectedBatch.taskCreatedAt) }} 创建，{{
                selectedBatch.resources.length
              }} 类资源，决策 {{ decisionLabel(selectedBatch.decision) }}。
            </p>
          </div>
          <div class="summary-stats">
            <span>{{ statusLabel(selectedBatch.status) }}</span>
            <strong>{{ selectedBatch.resources.length }}/3</strong>
          </div>
        </div>

        <div class="panel resource-detail">
          <el-tabs v-model="selectedResourceId" class="resource-tabs">
            <el-tab-pane
              v-for="resource in orderedBatchResources"
              :key="resource.resource_id"
              :label="typeLabel(resource.resource_type)"
              :name="resource.resource_id"
            />
          </el-tabs>

          <template v-if="selected">
            <div class="resource-head">
              <div>
                <h2>{{ selected.title }}</h2>
                <p class="muted">
                  {{ typeLabel(selected.resource_type) }} · 难度 {{ selected.difficulty }} ·
                  {{ formatDateTime(selected.generated_at) }}
                </p>
              </div>
              <el-tag :type="selected.review_status === 'passed' ? 'success' : 'warning'">
                {{ reviewLabel(selected.review_status) }}
              </el-tag>
            </div>

            <section>
              <h3>知识来源</h3>
              <div class="source-list">
                <el-tag
                  v-for="source in selected.source_details?.length ? selected.source_details : selected.sources"
                  :key="sourceKey(source)"
                  effect="plain"
                >
                  {{ sourceLabel(source) }}
                </el-tag>
              </div>
            </section>

            <section>
              <h3>资源内容</h3>
              <ResourceMarkdownViewer v-if="selected.content" :content="selected.content" />
              <p v-else class="muted">当前资源只有摘要，完整内容将在生成任务完成后写入。</p>
            </section>

            <section class="feedback-panel">
              <h3>学习反馈</h3>
              <p class="muted">选择学习者最直接的感受，系统会触发对应辅导动作。</p>
              <div class="feedback-row">
                <el-button @click="sendFeedback(selected.resource_id, 'too_easy')">
                  太简单，给挑战任务
                </el-button>
                <el-button @click="sendFeedback(selected.resource_id, 'too_hard')">
                  太难，补救解释
                </el-button>
                <el-button @click="sendFeedback(selected.resource_id, 'confusing')">
                  看不懂，重新讲解
                </el-button>
                <el-button type="warning" @click="sendFeedback(selected.resource_id, 'incorrect')">
                  有错误，触发修订
                </el-button>
              </div>
            </section>
          </template>
        </div>
      </main>
    </div>

    <div v-if="lastFeedback" class="panel feedback-result">
      <div>
        <h2 class="panel-title">反馈触发结果</h2>
        <p class="page-subtitle">
          {{ actionLabel(lastFeedback.triggered_action) }}，学习路径已标记为需要刷新。
        </p>
      </div>
      <el-descriptions :column="3" border>
        <el-descriptions-item label="资源">{{ lastFeedback.resource_id }}</el-descriptions-item>
        <el-descriptions-item label="触发智能体">{{ lastFeedback.triggered_agent }}</el-descriptions-item>
        <el-descriptions-item label="动作">{{ actionLabel(lastFeedback.triggered_action) }}</el-descriptions-item>
        <el-descriptions-item label="画像">{{ lastFeedback.profile_id }}</el-descriptions-item>
        <el-descriptions-item label="路径刷新">
          {{ lastFeedback.learning_path_needs_refresh ? '是' : '否' }}
        </el-descriptions-item>
      </el-descriptions>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { listResources, submitFeedback, type ResourceSummary } from '@/api/resources'
import ResourceMarkdownViewer from '@/components/ResourceViewer/ResourceMarkdownViewer.vue'

interface FeedbackResult {
  resource_id: string
  feedback_status: string
  triggered_agent: string
  triggered_action: string
  profile_id: string
  learning_path_needs_refresh: boolean
}

interface ResourceBatch {
  taskId: string
  status: string
  decision: string
  taskCreatedAt: string | null
  resources: ResourceSummary[]
  profileType: string
  targetDifficulty: number | null
}

const route = useRoute()
const router = useRouter()
const resources = ref<ResourceSummary[]>([])
const selectedTaskId = ref('')
const selectedResourceId = ref('')
const loading = ref(false)
const lastFeedback = ref<FeedbackResult | null>(null)

const requestedTaskId = computed(() => {
  const raw = route.query.task_id
  return typeof raw === 'string' && raw.trim() ? raw.trim() : ''
})

const batches = computed<ResourceBatch[]>(() => {
  const grouped = new Map<string, ResourceSummary[]>()
  for (const resource of resources.value) {
    const taskId = resource.generation_task_id || 'unknown_task'
    const current = grouped.get(taskId) ?? []
    current.push(resource)
    grouped.set(taskId, current)
  }
  return [...grouped.entries()].map(([taskId, batchResources]) => {
    const first = batchResources[0]
    return {
      taskId,
      status: first.generation_task_status || 'unknown',
      decision: first.generation_decision || 'pending',
      taskCreatedAt: first.task_created_at || first.generated_at || null,
      resources: batchResources,
      profileType: first.learner_profile_type || '',
      targetDifficulty: batchResources[0]?.difficulty ?? null,
    }
  })
})

const selectedBatch = computed(() => {
  return batches.value.find((batch) => batch.taskId === selectedTaskId.value) ?? null
})

const orderedBatchResources = computed(() => {
  const order: Record<string, number> = {
    lecture: 1,
    practice_guide: 2,
    graded_quiz: 3,
  }
  return [...(selectedBatch.value?.resources ?? [])].sort(
    (left, right) => (order[left.resource_type] ?? 99) - (order[right.resource_type] ?? 99),
  )
})

const selected = computed(() => {
  return (
    orderedBatchResources.value.find((resource) => resource.resource_id === selectedResourceId.value) ??
    orderedBatchResources.value[0] ??
    null
  )
})

function typeLabel(type: string) {
  return (
    {
      lecture: '讲义',
      practice_guide: '实训指导',
      graded_quiz: '分级测验',
    }[type] ?? type
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

function statusLabel(status: string) {
  return (
    {
      completed: '任务完成',
      running: '生成中',
      failed: '任务失败',
      revision_required: '需要修订',
      pending: '等待生成',
    }[status] ?? status
  )
}

function decisionLabel(decision: string) {
  return (
    {
      passed: '已通过',
      failed: '未通过',
      revision_required: '需要修订',
      pending: '等待决策',
    }[decision] ?? decision
  )
}

function actionLabel(action: string) {
  return (
    {
      challenge_task: '生成挑战任务',
      remedial_explanation: '生成补救解释',
      revision_required: '要求资源修订',
      profile_update: '更新学习画像',
    }[action] ?? action
  )
}

function sourceKey(source: string | { knowledge_id: string }) {
  return typeof source === 'string' ? source : source.knowledge_id
}

function sourceLabel(source: string | { knowledge_id: string; name?: string; source_title?: string }) {
  if (typeof source === 'string') return source
  return source.name ? `${source.name}（${source.knowledge_id}）` : source.knowledge_id
}

function formatDateTime(value?: string | null) {
  if (!value) return '时间未记录'
  const normalizedValue = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value)
    ? `${value}Z`
    : value
  const date = new Date(normalizedValue)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function isRequestedBatch(taskId: string) {
  return requestedTaskId.value ? requestedTaskId.value === taskId : selectedTaskId.value === taskId
}

function syncSelectionFromRoute() {
  if (!batches.value.length) {
    selectedTaskId.value = ''
    selectedResourceId.value = ''
    return
  }
  const nextTaskId =
    (requestedTaskId.value &&
      batches.value.find((batch) => batch.taskId === requestedTaskId.value)?.taskId) ||
    selectedTaskId.value ||
    batches.value[0].taskId
  selectedTaskId.value = nextTaskId
  const currentBatch = batches.value.find((batch) => batch.taskId === nextTaskId)
  if (
    currentBatch &&
    !currentBatch.resources.some((resource) => resource.resource_id === selectedResourceId.value)
  ) {
    selectedResourceId.value = currentBatch.resources[0]?.resource_id ?? ''
  }
}

function selectBatch(taskId: string) {
  selectedTaskId.value = taskId
  const batch = batches.value.find((item) => item.taskId === taskId)
  selectedResourceId.value = batch?.resources[0]?.resource_id ?? ''
  router.replace({ path: '/resources', query: { task_id: taskId } })
}

async function load() {
  loading.value = true
  try {
    resources.value = await listResources()
    syncSelectionFromRoute()
  } catch (error) {
    ElMessage.error('资源加载失败，请确认后端服务已启动。')
  } finally {
    loading.value = false
  }
}

async function sendFeedback(resourceId: string, feedbackType: string) {
  try {
    lastFeedback.value = (await submitFeedback(resourceId, feedbackType)) as FeedbackResult
    ElMessage.success('反馈已触发辅导动作。')
    await load()
  } catch (error) {
    ElMessage.error('反馈提交失败，请稍后重试。')
  }
}

watch(
  () => route.query.task_id,
  () => syncSelectionFromRoute(),
)

watch(batches, syncSelectionFromRoute)

watch(selected, (next) => {
  if (next && selectedResourceId.value !== next.resource_id) {
    selectedResourceId.value = next.resource_id
  }
})

onMounted(load)
</script>

<style scoped>
.resource-page {
  gap: 18px;
}

.loading-panel {
  min-height: 220px;
}

.empty-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 14px;
}

.resource-layout {
  display: grid;
  grid-template-columns: 330px minmax(0, 1fr);
  gap: 16px;
}

.batch-list,
.resource-main,
.resource-detail {
  display: grid;
  gap: 14px;
  align-self: start;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.batch-tab {
  display: grid;
  gap: 7px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-panel-soft);
  padding: 12px;
  color: var(--app-text);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 160ms ease,
    background 160ms ease;
}

.batch-tab:hover,
.batch-tab.is-active {
  border-color: #9bb8f5;
  background: var(--app-accent-soft);
}

.batch-topline,
.summary-kicker {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.batch-topline small,
.batch-meta,
.summary-kicker span {
  color: var(--app-muted);
  font-size: 12px;
}

.batch-tab strong {
  overflow-wrap: anywhere;
  font-size: 14px;
  line-height: 1.4;
}

.batch-summary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.batch-summary h2 {
  margin: 8px 0 0;
  font-size: 20px;
  line-height: 1.3;
}

.summary-stats {
  display: grid;
  gap: 6px;
  min-width: 90px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-panel-soft);
  padding: 12px;
  text-align: right;
}

.summary-stats span {
  color: var(--app-muted);
  font-size: 12px;
}

.summary-stats strong {
  font-size: 24px;
  line-height: 1;
}

.resource-tabs {
  min-width: 0;
}

.resource-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.resource-head h2 {
  margin: 0;
  font-size: 20px;
  line-height: 1.35;
}

.resource-detail h3 {
  margin: 0 0 10px;
  font-size: 15px;
}

.source-list,
.feedback-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.feedback-panel {
  border-top: 1px solid var(--app-border);
  padding-top: 16px;
}

.feedback-result {
  display: grid;
  gap: 14px;
}

@media (max-width: 980px) {
  .resource-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .batch-summary,
  .resource-head {
    display: grid;
  }

  .summary-stats {
    text-align: left;
  }
}
</style>
