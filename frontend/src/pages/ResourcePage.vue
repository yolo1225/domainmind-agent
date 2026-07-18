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

    <div v-else-if="requestedTaskId && pendingTask && !selectedBatch" class="panel generation-status-panel">
      <div class="section-head">
        <div>
          <h2 class="panel-title">
            {{ pendingTask.status === 'completed' ? '本次任务已完成' : '本次资源正在生成' }}
          </h2>
          <p class="page-subtitle">
            诊断画像已传入生成任务，系统正在完成知识检索、内容生成和双模型审核。
          </p>
        </div>
        <el-tag :type="pendingTask.status === 'waiting_human' ? 'warning' : 'primary'">
          {{ generationStatusLabel(pendingTask.status) }}
        </el-tag>
      </div>
      <el-progress
        :percentage="Math.max(0, Math.min(100, pendingTask.progress ?? 0))"
        :status="pendingTask.status === 'waiting_human' ? 'warning' : undefined"
      />
      <p class="muted generation-status-copy">
        {{ generationStatusDetail(pendingTask.status) }}任务编号：{{ shortTaskId(requestedTaskId) }}
      </p>
      <div class="empty-actions">
        <el-button :loading="loading" @click="load">刷新状态</el-button>
        <el-button @click="router.push({ path: '/agents', query: { task_id: requestedTaskId } })">
          查看 Agent 进度
        </el-button>
      </div>
    </div>

    <div v-else-if="requestedTaskId && !pendingTask && !selectedBatch" class="empty-hint">
      <strong>没有找到这次生成的资源</strong>
      <p>任务可能已失败或尚未返回状态，请刷新资源或前往 Agent 协同页查看进度。</p>
      <div class="empty-actions">
        <el-button :loading="loading" @click="load">刷新资源</el-button>
        <el-button @click="router.push('/agents')">查看 Agent 进度</el-button>
      </div>
    </div>

    <div v-else-if="!resources.length" class="empty-hint">
      <strong>还没有学习资源</strong>
      <p>请先完成诊断测评，或在 Agent 协同页启动一次生成流程。</p>
    </div>

    <div v-else class="resource-workspace">
      <div v-if="selectedBatch" class="current-batch-bar">
        <div class="current-batch-copy">
          <span class="batch-eyebrow">
            {{ isRequestedBatch(selectedBatch.taskId) ? '本次生成' : '当前查看批次' }}
          </span>
          <h2>{{ selectedBatch.taskId }}</h2>
          <p>
            {{ formatDateTime(selectedBatch.taskCreatedAt) }} 创建，{{
              selectedBatch.resources.length
            }}/3 类资源已入库，决策 {{ decisionLabel(selectedBatch.decision) }}。
          </p>
        </div>
        <div class="current-batch-metrics" aria-label="当前批次资源状态">
          <div>
            <span>任务状态</span>
            <strong>{{ statusLabel(selectedBatch.status) }}</strong>
          </div>
          <div>
            <span>审核通过</span>
            <strong>{{ batchPassedCount(selectedBatch) }}/{{ selectedBatch.resources.length }}</strong>
          </div>
          <div>
            <span>知识来源</span>
            <strong>{{ batchSourceCount(selectedBatch) }}</strong>
          </div>
        </div>
      </div>

      <div class="resource-layout">
        <aside class="panel batch-list">
          <div class="section-head">
            <div>
              <h2 class="panel-title">生成批次</h2>
              <p class="panel-caption">按任务查看每次生成的三类资源</p>
            </div>
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
            <span class="batch-marker" aria-hidden="true" />
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
            <strong>{{ shortTaskId(batch.taskId) }}</strong>
            <span class="batch-meta">
              {{ batch.resources.length }} 类资源 · {{ decisionLabel(batch.decision) }}
            </span>
            <span class="batch-meta">
              画像 {{ batch.profileType || '未标注' }} · 难度 {{ batch.targetDifficulty || '-' }}
            </span>
            <span class="batch-resource-dots" aria-label="资源类型">
              <i
                v-for="item in resourceTypeChecklist(batch)"
                :key="item.type"
                :class="{ 'is-ready': item.ready }"
              >
                {{ item.label }}
              </i>
            </span>
          </button>
        </aside>

        <main v-if="selectedBatch" class="resource-main">
          <div class="resource-switcher">
            <button
              v-for="resource in orderedBatchResources"
              :key="resource.resource_id"
              class="resource-chip"
              :class="{ 'is-active': selectedResourceId === resource.resource_id }"
              type="button"
              @click="selectedResourceId = resource.resource_id"
            >
              <span>{{ typeLabel(resource.resource_type) }}</span>
              <strong>{{ resource.title }}</strong>
              <small>难度 {{ resource.difficulty }} · {{ reviewLabel(resource.review_status) }}</small>
            </button>
          </div>

          <div class="panel resource-detail">
            <template v-if="selected">
              <div class="resource-head">
                <div>
                  <h2>{{ selected.title }}</h2>
                  <p class="muted">
                    {{ typeLabel(selected.resource_type) }} · 难度 {{ selected.difficulty }} ·
                    {{ formatDateTime(selected.generated_at) }}
                  </p>
                </div>
                <div class="resource-actions">
                  <el-tag :type="selected.review_status === 'passed' ? 'success' : 'warning'">
                    {{ reviewLabel(selected.review_status) }}
                  </el-tag>
                  <el-button size="small" @click="showVersions">版本记录</el-button>
                  <el-dropdown @command="downloadResource">
                    <el-button size="small">导出</el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="markdown:learner">Markdown 学习者版</el-dropdown-item>
                        <el-dropdown-item command="pdf:learner">PDF 学习者版</el-dropdown-item>
                        <el-dropdown-item v-if="selected.resource_type === 'graded_quiz'" command="markdown:teacher">Markdown 教师版</el-dropdown-item>
                        <el-dropdown-item v-if="selected.resource_type === 'graded_quiz'" command="pdf:teacher">PDF 教师版</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </div>

              <div class="resource-facts">
                <div>
                  <span>资源类型</span>
                  <strong>{{ typeLabel(selected.resource_type) }}</strong>
                </div>
                <div>
                  <span>目标难度</span>
                  <strong>{{ selected.difficulty }}</strong>
                </div>
                <div>
                  <span>知识来源</span>
                  <strong>{{ resourceSourceCount(selected) }}</strong>
                </div>
              </div>

              <section class="source-section">
                <div class="section-title-row">
                  <h3>知识来源</h3>
                  <span>{{ resourceSourceCount(selected) }} 条可追溯引用</span>
                </div>
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

              <section class="content-section">
                <h3>资源内容</h3>
                <ResourceMarkdownViewer v-if="selected.content" :content="selected.content" />
                <p v-else class="muted">当前资源只有摘要，完整内容将在生成任务完成后写入。</p>
              </section>

              <section class="feedback-panel">
                <div>
                  <h3>学习反馈</h3>
                  <p class="muted">选择学习者最直接的感受，系统会触发对应辅导动作。</p>
                </div>
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
                <div class="tutoring-box">
                  <div class="section-title-row">
                    <h3>连续导学</h3>
                    <el-tag v-if="tutoringSessionId" effect="plain">会话进行中</el-tag>
                  </div>
                  <div v-if="tutoringMessages.length" class="tutoring-messages">
                    <p v-for="message in tutoringMessages" :key="message.id" :class="message.sender">
                      <strong>{{ message.sender === 'learner' ? '我' : '导学 Agent' }}</strong>
                      <span>{{ message.content }}</span>
                    </p>
                  </div>
                  <el-button
                    v-if="tutoringTaskId"
                    type="primary"
                    plain
                    @click="router.push({ path: '/agents', query: { task_id: tutoringTaskId } })"
                  >
                    查看本次导学协同进度
                  </el-button>
                  <div class="tutoring-input">
                    <el-input
                      v-model="tutoringInput"
                      placeholder="描述你具体不理解的地方"
                      @keyup.enter="sendTutorMessage"
                    />
                    <el-button type="primary" :loading="tutoringSending" @click="sendTutorMessage">发送</el-button>
                  </div>
                </div>
              </section>
            </template>
          </div>
        </main>
      </div>
    </div>

    <div v-if="lastFeedback" class="panel feedback-result">
      <div>
        <h2 class="panel-title">反馈触发结果</h2>
        <p class="page-subtitle">
          {{ actionLabel(lastFeedback.recommended_action) }}。{{ lastFeedback.decision_reason }}
        </p>
      </div>
      <el-descriptions :column="3" border>
        <el-descriptions-item label="资源">{{ lastFeedback.resource_id }}</el-descriptions-item>
        <el-descriptions-item label="反馈意图">{{ lastFeedback.feedback_intent || '未知状态' }}</el-descriptions-item>
        <el-descriptions-item label="建议动作">{{ actionLabel(lastFeedback.recommended_action) }}</el-descriptions-item>
        <el-descriptions-item label="画像更新">
          {{ lastFeedback.profile_update_required ? '已更新' : '证据不足，不更新' }}
        </el-descriptions-item>
        <el-descriptions-item label="后续任务">
          {{ lastFeedback.task_id || '无需创建任务' }}
        </el-descriptions-item>
      </el-descriptions>
      <el-button
        v-if="lastFeedback.task_id"
        type="primary"
        @click="router.push({ path: '/agents', query: { task_id: lastFeedback.task_id } })"
      >
        查看协同进度
      </el-button>
    </div>

    <el-drawer v-model="versionsVisible" title="资源版本记录" size="420px">
      <el-timeline v-if="versions.length">
        <el-timeline-item v-for="item in versions" :key="item.resource_id" :timestamp="formatDateTime(item.created_at)">
          <strong>版本 {{ item.version }}</strong>
          <el-tag v-if="item.is_current" size="small" type="success">当前版本</el-tag>
          <p>{{ reviewLabel(item.review_status) }} · {{ item.adaptation_reason || '首次生成' }}</p>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无版本记录" />
    </el-drawer>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import {
  exportResource,
  listResources,
  listResourceVersions,
  submitFeedback,
  type ResourceSummary,
} from '@/api/resources'
import { getGenerationTask } from '@/api/generation'
import { createTutoringSession, sendTutoringMessage } from '@/api/tutoring'
import ResourceMarkdownViewer from '@/components/ResourceViewer/ResourceMarkdownViewer.vue'
import { useLearnerStore } from '@/stores/learnerStore'

interface FeedbackResult {
  resource_id: string
  feedback_status: string
  feedback_intent: string | null
  recommended_action: string
  profile_update_required: boolean
  decision_reason: string
  task_id: string | null
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
const learnerStore = useLearnerStore()
const resources = ref<ResourceSummary[]>([])
const selectedTaskId = ref('')
const selectedResourceId = ref('')
const loading = ref(false)
const lastFeedback = ref<FeedbackResult | null>(null)
const versionsVisible = ref(false)
const versions = ref<Awaited<ReturnType<typeof listResourceVersions>>>([])
const tutoringSessionId = ref('')
const tutoringInput = ref('')
const tutoringSending = ref(false)
const tutoringMessages = ref<Array<{ id: string; sender: 'learner' | 'agent'; content: string }>>([])
const tutoringTaskId = ref<string | null>(null)
const pendingTask = ref<Awaited<ReturnType<typeof getGenerationTask>> | null>(null)
let generationPollTimer: number | null = null

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
    }[status] ?? '未知状态'
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
    }[status] ?? '未知状态'
  )
}

function decisionLabel(decision: string) {
  return (
    {
      passed: '已通过',
      failed: '未通过',
      revision_required: '需要修订',
      pending: '等待决策',
    }[decision] ?? '未知状态'
  )
}

function actionLabel(action: string) {
  return (
    {
      challenge: '生成挑战任务',
      explain: '给出补救解释',
      review: '复核资源事实',
      regenerate: '局部重新生成',
      update_profile: '更新学习画像',
      update_path: '刷新学习路径',
      no_change: '记录反馈，不修改画像',
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

function shortTaskId(taskId: string) {
  if (taskId.length <= 18) return taskId
  return `${taskId.slice(0, 10)}...${taskId.slice(-6)}`
}

function resourceSourceCount(resource: ResourceSummary) {
  return resource.source_details?.length || resource.sources?.length || 0
}

function batchSourceCount(batch: ResourceBatch) {
  return new Set(
    batch.resources.flatMap((resource) =>
      resource.source_details?.length
        ? resource.source_details.map((source) => source.knowledge_id)
        : resource.sources,
    ),
  ).size
}

function batchPassedCount(batch: ResourceBatch) {
  return batch.resources.filter((resource) => resource.review_status === 'passed').length
}

function resourceTypeChecklist(batch: ResourceBatch) {
  const readyTypes = new Set(batch.resources.map((resource) => resource.resource_type))
  return [
    { type: 'lecture', label: '讲义', ready: readyTypes.has('lecture') },
    { type: 'practice_guide', label: '实训', ready: readyTypes.has('practice_guide') },
    { type: 'graded_quiz', label: '测验', ready: readyTypes.has('graded_quiz') },
  ]
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
    year: 'numeric',
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
  if (requestedTaskId.value && !batches.value.some((batch) => batch.taskId === requestedTaskId.value)) {
    selectedTaskId.value = requestedTaskId.value
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

function generationStatusLabel(status: string) {
  return ({
    pending: '排队中',
    running: '生成中',
    waiting_human: '等待人工审核',
    completed: '已完成',
    failed: '生成失败',
  } as Record<string, string>)[status] || '处理中'
}

function generationStatusDetail(status: string) {
  return ({
    pending: '任务已创建，正在排队。',
    running: '正在执行多智能体协同流程，请稍候。',
    waiting_human: '双模型审核存在分歧，需要管理员确认后才会发布资源。',
    completed: '任务已完成，但资源列表正在同步。',
    failed: '任务执行失败，请查看 Agent 运行记录。',
  } as Record<string, string>)[status] || '系统正在处理任务。'
}

function stopGenerationPolling() {
  if (generationPollTimer !== null) {
    window.clearInterval(generationPollTimer)
    generationPollTimer = null
  }
}

async function refreshGenerationStatus() {
  if (!requestedTaskId.value) {
    pendingTask.value = null
    stopGenerationPolling()
    return
  }
  try {
    const task = await getGenerationTask(requestedTaskId.value)
    pendingTask.value = task
    if (task.status === 'completed' || task.status === 'failed' || task.status === 'waiting_human') {
      stopGenerationPolling()
      await loadResources()
    }
  } catch {
    pendingTask.value = null
  }
}

async function loadResources() {
  resources.value = await listResources()
  syncSelectionFromRoute()
}

function startGenerationPolling() {
  stopGenerationPolling()
  if (!requestedTaskId.value) return
  void refreshGenerationStatus()
  generationPollTimer = window.setInterval(() => void refreshGenerationStatus(), 2000)
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
    await loadResources()
    await refreshGenerationStatus()
  } catch (error) {
    ElMessage.error('资源加载失败，请确认后端服务已启动。')
  } finally {
    loading.value = false
  }
}

async function sendFeedback(resourceId: string, feedbackType: string) {
  try {
    lastFeedback.value = (await submitFeedback(
      resourceId,
      feedbackType,
      3,
      learnerStore.selectedLearnerId,
    )) as FeedbackResult
    ElMessage.success('反馈已触发辅导动作。')
    await load()
  } catch (error) {
    ElMessage.error('反馈提交失败，请稍后重试。')
  }
}

async function showVersions() {
  if (!selected.value) return
  versionsVisible.value = true
  try { versions.value = await listResourceVersions(selected.value.resource_id) }
  catch { ElMessage.error('版本记录加载失败') }
}

async function downloadResource(command: string) {
  if (!selected.value) return
  const [format, audience] = command.split(':') as ['markdown' | 'pdf', 'learner' | 'teacher']
  try {
    const result = await exportResource(selected.value.resource_id, format, audience)
    window.open(result.download_url, '_blank', 'noopener')
    ElMessage.success(`已生成版本 ${result.resource_version} 的${audience === 'teacher' ? '教师版' : '学习者版'}${format === 'pdf' ? ' PDF' : ' Markdown'}文件`)
  } catch { ElMessage.error('资源导出失败') }
}

async function sendTutorMessage() {
  if (!selected.value || !tutoringInput.value.trim()) return
  const content = tutoringInput.value.trim()
  tutoringSending.value = true
  try {
    if (!tutoringSessionId.value) {
      const session = await createTutoringSession(selected.value.resource_id, learnerStore.selectedLearnerId)
      tutoringSessionId.value = session.session_id
    }
    tutoringMessages.value.push({ id: `local-${Date.now()}`, sender: 'learner', content })
    tutoringInput.value = ''
    const result = await sendTutoringMessage(tutoringSessionId.value, content)
    tutoringMessages.value.push({ id: result.reply.message_id, sender: 'agent', content: result.reply.content })
    tutoringTaskId.value = result.task_id
    ElMessage.info(result.profile_update_required ? '画像已基于证据创建新版本' : '当前证据不足，画像保持不变')
  } catch { ElMessage.error('导学消息发送失败') }
  finally { tutoringSending.value = false }
}

watch(
  () => route.query.task_id,
  () => {
    syncSelectionFromRoute()
    startGenerationPolling()
  },
)

watch(batches, syncSelectionFromRoute)

watch(selected, (next, previous) => {
  if (next && selectedResourceId.value !== next.resource_id) {
    selectedResourceId.value = next.resource_id
  }
  if (next?.resource_id !== previous?.resource_id) {
    tutoringSessionId.value = ''
    tutoringMessages.value = []
  }
})

onMounted(load)
onBeforeUnmount(stopGenerationPolling)
</script>

<style scoped>
.resource-page {
  gap: 18px;
}

.resource-actions,
.tutoring-input {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tutoring-box {
  display: grid;
  gap: 12px;
  margin-top: 16px;
  border-top: 1px solid var(--app-border);
  padding-top: 16px;
}

.tutoring-messages {
  display: grid;
  gap: 8px;
  max-height: 260px;
  overflow: auto;
}

.tutoring-messages p {
  display: grid;
  gap: 3px;
  margin: 0;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-panel-soft);
  padding: 7px 10px;
  color: var(--app-muted);
}

.tutoring-messages p.agent {
  border-color: #b9cdf8;
  background: var(--app-accent-soft);
}

.loading-panel {
  min-height: 220px;
}

.generation-status-panel {
  display: grid;
  gap: 14px;
}

.generation-status-copy {
  margin: 0;
  line-height: 1.7;
}

.empty-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 14px;
}

.resource-workspace {
  display: grid;
  gap: 16px;
}

.current-batch-bar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 0.72fr);
  gap: 16px;
  border: 1px solid #b9cdf8;
  border-radius: 10px;
  background:
    linear-gradient(90deg, rgb(37 99 235 / 0.11), rgb(8 145 178 / 0.08)),
    var(--app-panel);
  padding: 18px;
}

.current-batch-copy {
  min-width: 0;
}

.batch-eyebrow {
  display: inline-flex;
  align-items: center;
  border: 1px solid rgb(37 99 235 / 0.25);
  border-radius: 999px;
  background: #fff;
  padding: 3px 10px;
  color: var(--app-accent);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.5;
}

.current-batch-copy h2 {
  margin: 10px 0 6px;
  overflow-wrap: anywhere;
  color: var(--app-text);
  font-size: 20px;
  line-height: 1.35;
}

.current-batch-copy p {
  margin: 0;
  color: #344054;
  font-size: 14px;
  line-height: 1.7;
}

.current-batch-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  align-self: stretch;
}

.current-batch-metrics div,
.resource-facts div {
  display: grid;
  gap: 7px;
  min-width: 0;
  border: 1px solid rgb(219 228 239 / 0.9);
  border-radius: 8px;
  background: rgb(255 255 255 / 0.82);
  padding: 12px;
}

.current-batch-metrics span,
.resource-facts span,
.panel-caption {
  color: var(--app-muted);
  font-size: 12px;
  line-height: 1.5;
}

.current-batch-metrics strong,
.resource-facts strong {
  min-width: 0;
  overflow: hidden;
  color: var(--app-text);
  font-size: 16px;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resource-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
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

.panel-caption {
  margin: -6px 0 0;
}

.batch-tab {
  position: relative;
  display: grid;
  gap: 7px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: #fff;
  padding: 12px 12px 12px 18px;
  color: var(--app-text);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 160ms ease,
    background 160ms ease,
    transform 160ms ease;
}

.batch-tab:hover,
.batch-tab.is-active {
  border-color: #9bb8f5;
  background: var(--app-accent-soft);
}

.batch-tab:hover {
  transform: translateY(-1px);
}

.batch-marker {
  position: absolute;
  top: 13px;
  bottom: 13px;
  left: 8px;
  width: 3px;
  border-radius: 999px;
  background: #cbd5e1;
}

.batch-tab.is-active .batch-marker {
  background: var(--app-accent);
}

.batch-topline {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.batch-topline small,
.batch-meta {
  color: var(--app-muted);
  font-size: 12px;
}

.batch-tab strong {
  overflow-wrap: anywhere;
  font-size: 14px;
  line-height: 1.4;
}

.batch-resource-dots {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.batch-resource-dots i {
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: var(--app-panel-soft);
  padding: 2px 7px;
  color: var(--app-muted);
  font-size: 12px;
  font-style: normal;
  line-height: 1.5;
}

.batch-resource-dots i.is-ready {
  border-color: rgb(22 163 74 / 0.28);
  background: rgb(22 163 74 / 0.08);
  color: #15803d;
}

.resource-switcher {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.resource-chip {
  display: grid;
  gap: 5px;
  min-width: 0;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-panel);
  padding: 13px;
  color: var(--app-text);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 160ms ease,
    background 160ms ease;
}

.resource-chip:hover,
.resource-chip.is-active {
  border-color: #9bb8f5;
  background: var(--app-accent-soft);
}

.resource-chip span {
  color: var(--app-accent);
  font-size: 12px;
  font-weight: 700;
}

.resource-chip strong {
  overflow: hidden;
  font-size: 14px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resource-chip small {
  color: var(--app-muted);
  font-size: 12px;
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

.resource-facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.resource-detail h3 {
  margin: 0 0 10px;
  font-size: 15px;
}

.section-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-title-row span {
  color: var(--app-muted);
  font-size: 12px;
}

.source-list,
.feedback-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.source-section,
.content-section,
.feedback-panel {
  border-top: 1px solid var(--app-border);
  padding-top: 16px;
}

.feedback-panel {
  display: grid;
  gap: 12px;
  border-radius: 8px;
  background: var(--app-panel-soft);
  padding: 16px;
}

.feedback-panel h3,
.feedback-panel p {
  margin-left: 0;
}

.feedback-result {
  display: grid;
  gap: 14px;
}

@media (prefers-reduced-motion: reduce) {
  .batch-tab,
  .resource-chip {
    transition: none;
  }

  .batch-tab:hover {
    transform: none;
  }
}

@media (max-width: 1160px) {
  .current-batch-bar {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 980px) {
  .resource-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .current-batch-metrics,
  .resource-switcher,
  .resource-facts {
    grid-template-columns: 1fr;
  }

  .resource-head,
  .section-title-row {
    display: grid;
  }
}
</style>
