<template>
  <section class="page agent-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Agent 协同工作台</h1>
        <p class="page-subtitle">统一展示首次生成、反馈触发、双模型复审和人工复核的同一条任务链。</p>
      </div>
      <div class="toolbar">
        <el-button v-if="requestedTaskId" :loading="loadingTask" @click="loadTask">刷新任务</el-button>
        <el-button
          v-if="requestedTaskId && taskDetail?.status === 'completed'"
          type="primary"
          @click="router.push({ path: '/resources', query: { task_id: requestedTaskId } })"
        >
          查看本次资源
        </el-button>
      </div>
    </div>

    <el-alert v-if="taskError" class="panel" type="error" show-icon :title="taskError">
      <template #default>
        <el-button size="small" @click="loadTask">重试</el-button>
      </template>
    </el-alert>

    <div v-else-if="!requestedTaskId && loadingTask" class="panel">
      <el-skeleton :rows="4" animated />
    </div>

    <div v-else-if="!requestedTaskId" class="empty-hint">
      <strong>请选择一个任务查看协同进度</strong>
      <p>请从诊断、学情画像或资源反馈页面进入“查看协同进度”。</p>
    </div>

    <template v-else>
    <div class="summary-strip">
      <div><span>任务 / Thread</span><strong>{{ taskStore.currentTaskId || '未启动' }}</strong></div>
      <div><span>触发类型</span><strong>{{ triggerType }}</strong></div>
      <div><span>当前节点</span><strong>{{ stepLabel(activeStep) }}</strong></div>
      <div><span>反馈意图</span><strong>{{ feedbackIntent }}</strong></div>
      <div><span>画像结论</span><strong>{{ profileDecision }}</strong></div>
      <div><span>任务决策</span><strong>{{ decisionLabel(taskStore.latestDecision) }}</strong></div>
      <div><span>画像版本</span><strong>{{ taskDetail?.profile_version || '-' }}</strong></div>
      <div><span>任务进度</span><strong>{{ taskDetail?.progress ?? 0 }}%</strong></div>
    </div>

    <div class="workspace-grid">
      <div class="panel">
        <div class="section-head">
          <h2 class="panel-title">统一八节点工作流</h2>
          <el-tag v-if="waitingHuman" type="danger">等待人工复核</el-tag>
          <el-tag v-else-if="hasRevisionLoop" type="warning">自动修订中</el-tag>
        </div>
        <AgentFlowView
          :active-step="activeStep"
          :has-revision-loop="hasRevisionLoop"
          :waiting-human="waitingHuman"
        />
      </div>

      <div class="panel event-panel">
        <div class="section-head">
          <h2 class="panel-title">运行事件</h2>
          <el-tag effect="plain">{{ taskStore.events.length }} 条</el-tag>
        </div>
        <el-timeline v-if="taskStore.events.length" class="event-list">
          <el-timeline-item
            v-for="(event, index) in taskStore.events"
            :key="`${event.event_type}-${event.run_id}-${index}`"
            :type="eventType(event.status)"
            :timestamp="event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : ''"
          >
            <strong>{{ eventName(event.event_type, event.step) }}</strong>
            <p>{{ event.event_message || statusLabel(event.status) }}</p>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="启动任务后显示数据库中的真实 Agent 运行记录" />
      </div>
    </div>

    <div class="panel arbitration-panel">
      <div class="section-head">
        <h2 class="panel-title">双模型审核与仲裁</h2>
        <el-tag :type="reviewConflict ? 'danger' : 'success'">
          {{ reviewConflict ? '存在审核冲突' : '暂无未解决冲突' }}
        </el-tag>
      </div>
      <div class="review-grid">
        <div><span>主审核模型</span><strong>{{ reviewScore('primary') }}</strong></div>
        <div><span>次审核模型</span><strong>{{ reviewScore('secondary') }}</strong></div>
        <div><span>重新检索证据</span><strong>{{ reviewEvidenceCount }} 条</strong></div>
        <div><span>最终仲裁</span><strong>{{ waitingHuman ? '等待管理员决定' : decisionLabel(taskStore.latestDecision) }}</strong></div>
      </div>
      <p class="scope-line">影响范围：{{ affectedScope }}</p>
    </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { subscribeTaskEvents } from '@/api/client'
import { getActiveGenerationTask, getGenerationTask } from '@/api/generation'
import AgentFlowView from '@/components/AgentFlow/AgentFlowView.vue'
import { useLearnerStore } from '@/stores/learnerStore'
import { useTaskStore } from '@/stores/taskStore'
import { resolveAgentTaskId } from '@/utils/agentTaskRecovery'

const taskStore = useTaskStore()
const learnerStore = useLearnerStore()
const route = useRoute()
const router = useRouter()
const loadingTask = ref(false)
const taskError = ref('')
const taskDetail = ref<Awaited<ReturnType<typeof getGenerationTask>> | null>(null)
let source: EventSource | null = null
let pollTimer: number | null = null

const requestedTaskId = computed(() => {
  const raw = route.query.task_id
  return typeof raw === 'string' && raw.trim() ? raw.trim() : ''
})

const activeStep = computed(() =>
  [...taskStore.events].reverse().find((item) => item.step && item.step !== 'task')?.step,
)
const waitingHuman = computed(() =>
  taskStore.events.some((item) => item.event_type === 'manual_review_required'),
)
const hasRevisionLoop = computed(() =>
  taskStore.events.some((item) => (item.generation_round || 0) > 1),
)
const reviewConflict = computed(() =>
  taskStore.events.some((item) => item.event_type === 'review_disagreement'),
)
const reviewReport = computed<Record<string, unknown> | null>(() => {
  const event = [...taskStore.events].reverse().find((item) => Array.isArray(item.payload?.resource_reviews))
  const reports = event?.payload?.resource_reviews
  return Array.isArray(reports) && reports.length ? reports[0] as Record<string, unknown> : null
})
const reviewEvidenceCount = computed(() => {
  const arbitration = reviewReport.value?.arbitration as Record<string, unknown> | undefined
  const evidence = arbitration?.retrieved_evidence_refs
  return Array.isArray(evidence) ? evidence.length : 0
})
const triggerType = computed(() => String(latestPayload('trigger_type') || '首次生成'))
const feedbackIntent = computed(() => String(latestPayload('feedback_intent') || '不适用'))
const profileDecision = computed(() => {
  if (taskStore.events.some((item) => item.event_type === 'profile_updated')) return '已基于证据更新'
  if (taskStore.events.some((item) => item.event_type === 'profile_unchanged')) return '证据不足，不更新'
  return '待判断'
})
const affectedScope = computed(() => {
  const knowledge = latestPayload('affected_knowledge_ids')
  return Array.isArray(knowledge) && knowledge.length ? knowledge.join('、') : '无局部更新'
})

function latestPayload(key: string) {
  return [...taskStore.events].reverse().find((item) => item.payload?.[key] !== undefined)?.payload?.[key]
}
function reviewScore(role: 'primary' | 'secondary') {
  const report = reviewReport.value
  if (!report) return '等待审核'
  const arbitration = report.arbitration as Record<string, unknown> | undefined
  const recheck = arbitration?.recheck_scores as Record<string, unknown> | undefined
  const channel = (recheck?.[role] || report[`${role}_review`]) as Record<string, unknown> | undefined
  if (!channel) return '未知状态'
  const scores = ['factual_score', 'source_trace_score', 'difficulty_match_score', 'coverage_score']
    .map((key) => Number(channel[key]))
    .filter((value) => Number.isFinite(value))
  const average = scores.length ? scores.reduce((sum, value) => sum + value, 0) / scores.length : 0
  return `${average.toFixed(1)} 分 · ${channel.passed ? '通过' : '未通过'}`
}
function stepLabel(step?: string) {
  const labels: Record<string, string> = {
    prepare_task: '任务准备', interpret_feedback: '反馈识别', analyze_profile: '画像分析',
    retrieve_knowledge: '知识检索', generate_resource: '资源生成', review_resource: '双模型审核',
    human_review: '人工复核', finalize_task: '任务收尾',
  }
  return step ? labels[step] || '未知状态' : '待启动'
}
function eventName(type?: string, step?: string) {
  const names: Record<string, string> = {
    trigger_routed: '触发已路由', feedback_classified: '反馈已分类',
    profile_update_decided: '画像更新已判断', profile_updated: '画像已创建新版本',
    profile_unchanged: '画像保持不变', review_disagreement: '双模型结论冲突',
    review_retrieval_started: '重新检索证据', manual_review_required: '需要人工复核',
    manual_review_resolved: '人工复核已解决', resource_created: '资源版本已创建',
    task_completed: '任务完成', task_failed: '任务失败', agent_status: stepLabel(step),
  }
  return names[type || ''] || '未知状态'
}
function statusLabel(status: string) {
  return ({ running: '运行中', completed: '已完成', failed: '失败', waiting_human: '等待人工复核' } as Record<string, string>)[status] || '未知状态'
}
function decisionLabel(value: string) {
  return ({ pending: '待处理', completed: '已通过', no_change: '无需变更', failed: '失败', rejected: '已驳回', manual_review_required: '人工复核' } as Record<string, string>)[value] || '未知状态'
}
function eventType(status: string) {
  if (status === 'failed') return 'danger'
  if (status === 'completed') return 'success'
  return 'primary'
}
function stopMonitoring() {
  source?.close()
  source = null
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

async function loadTask() {
  const explicitTaskId = requestedTaskId.value
  stopMonitoring()
  taskError.value = ''
  taskDetail.value = null
  taskStore.clearTask()
  loadingTask.value = true
  try {
    const taskId = await resolveAgentTaskId(
      explicitTaskId,
      learnerStore.selectedLearnerId,
      getActiveGenerationTask,
    )
    if (!taskId) return
    if (!explicitTaskId) {
      await router.replace({ path: '/agents', query: { task_id: taskId } })
      return
    }
    taskDetail.value = await getGenerationTask(taskId)
    taskStore.setTask(taskId)
    source = subscribeTaskEvents(taskId, async (event) => {
      taskStore.addEvent(event)
      if (['task_completed', 'task_failed', 'manual_review_required'].includes(event.event_type || '')) {
        try {
          taskDetail.value = await getGenerationTask(taskId)
        } finally {
          stopMonitoring()
        }
      }
    })
    pollTimer = window.setInterval(async () => {
      try {
        taskDetail.value = await getGenerationTask(taskId)
        if (['completed', 'failed', 'waiting_human'].includes(taskDetail.value.status)) {
          stopMonitoring()
        }
      } catch {
        taskError.value = '任务状态查询失败，请重试。'
      }
    }, 2000)
  } catch {
    taskError.value = explicitTaskId
      ? '没有找到该任务，或任务状态暂时不可用。'
      : '当前学习者的运行中任务查询失败，请稍后重试。'
    ElMessage.error(taskError.value)
  } finally {
    loadingTask.value = false
  }
}

watch(requestedTaskId, loadTask)
watch(
  () => learnerStore.selectedLearnerId,
  () => {
    if (!requestedTaskId.value) loadTask()
  },
)
onMounted(loadTask)
onBeforeUnmount(stopMonitoring)
</script>

<style scoped>
.agent-page { gap: 18px; }
.summary-strip { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
.summary-strip > div, .review-grid > div { display: grid; gap: 6px; min-width: 0; border: 1px solid var(--app-border); border-radius: 8px; background: var(--app-panel); padding: 12px; }
.summary-strip span, .review-grid span { color: var(--app-muted); font-size: 12px; }
.summary-strip strong, .review-grid strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workspace-grid { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(320px, .6fr); gap: 16px; }
.section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.event-list { max-height: 390px; overflow: auto; padding-right: 6px; }
.event-list p { margin: 4px 0 0; color: var(--app-muted); font-size: 13px; }
.review-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.scope-line { margin: 12px 0 0; color: var(--app-muted); font-size: 13px; }
@media (max-width: 1100px) { .summary-strip { grid-template-columns: repeat(3, 1fr); } .workspace-grid { grid-template-columns: 1fr; } .review-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 700px) { .summary-strip, .review-grid { grid-template-columns: 1fr; } }
</style>
