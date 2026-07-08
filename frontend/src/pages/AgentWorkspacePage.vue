<template>
  <section class="page agent-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Agent 协作工作台</h1>
        <p class="page-subtitle">
          展示画像、检索、生成、审核、决策和修订回路的真实运行摘要，用于解释多智能体协作过程。
        </p>
      </div>
      <div class="toolbar">
        <el-button
          v-if="canViewCurrentResources"
          @click="router.push({ path: '/resources', query: { task_id: taskStore.currentTaskId } })"
        >
          查看本次资源
        </el-button>
        <el-button type="primary" :loading="starting" @click="startDemo">启动协同流</el-button>
      </div>
    </div>

    <div class="summary-strip">
      <div class="summary-item">
        <span>任务</span>
        <strong>{{ taskStore.currentTaskId || '未启动' }}</strong>
      </div>
      <div class="summary-item">
        <span>当前轮次</span>
        <strong>{{ taskStore.currentRound || '-' }}</strong>
      </div>
      <div class="summary-item">
        <span>策略</span>
        <strong>{{ strategyLabel(taskStore.latestStrategy) }}</strong>
      </div>
      <div class="summary-item">
        <span>目标难度</span>
        <strong>{{ taskStore.latestDifficulty ?? '-' }}</strong>
      </div>
      <div class="summary-item">
        <span>平均审核分</span>
        <strong>{{ taskStore.latestAverageScore ?? '-' }}</strong>
      </div>
      <div class="summary-item">
        <span>决策</span>
        <strong>{{ decisionLabel(taskStore.latestDecision) }}</strong>
      </div>
    </div>

    <div class="agent-grid">
      <div class="panel graph-panel">
        <div class="section-head">
          <h2 class="panel-title">工作流拓扑</h2>
          <el-tag v-if="hasRevisionLoop" type="warning" effect="plain">修订回路已触发</el-tag>
        </div>
        <AgentFlowView
          :active-step="activeStep"
          :current-round="taskStore.currentRound"
          :has-revision-loop="hasRevisionLoop"
        />
      </div>

      <div class="panel event-panel">
        <div class="section-head">
          <h2 class="panel-title">实时事件</h2>
          <el-tag v-if="taskStore.events.length" effect="plain">{{ taskStore.events.length }} 条</el-tag>
        </div>
        <el-timeline v-if="taskStore.events.length" class="event-timeline">
          <el-timeline-item
            v-for="(event, index) in taskStore.events"
            :key="`${event.step}-${event.status}-${index}`"
            :type="timelineType(event.status)"
            :timestamp="eventTimestamp(event)"
          >
            <div class="event-row">
              <div class="event-title">
                <strong>{{ stepLabel(event.step) }}</strong>
                <el-tag v-if="event.generation_round" size="small" effect="plain">
                  第 {{ event.generation_round }} 轮
                </el-tag>
                <el-tag v-if="event.is_revision_round" size="small" type="warning" effect="plain">
                  修订
                </el-tag>
              </div>
              <p>{{ event.event_message || stepDescription(event.step) }}</p>
              <div v-if="payloadSummary(event).length" class="event-facts">
                <span v-for="fact in payloadSummary(event)" :key="fact">{{ fact }}</span>
              </div>
            </div>
          </el-timeline-item>
        </el-timeline>
        <div v-else class="empty-hint">
          <strong>等待任务启动</strong>
          <p>点击“启动协同流”，前端会订阅 SSE 事件并同步更新流程图。</p>
        </div>
      </div>
    </div>

    <div class="panel revision-panel">
      <div class="section-head">
        <h2 class="panel-title">修订闭环</h2>
        <el-tag :type="hasRevisionLoop ? 'warning' : 'success'" effect="plain">
          {{ hasRevisionLoop ? '已进入修订' : '等待审核决策' }}
        </el-tag>
      </div>
      <div class="revision-grid">
        <div>
          <span class="field-label">需重生成资源</span>
          <strong>{{ resourceTypesText(taskStore.latestRevisionTypes) || '暂无' }}</strong>
        </div>
        <div>
          <span class="field-label">缺失要求</span>
          <strong>{{ listText(taskStore.latestMissingRequirements) || '暂无' }}</strong>
        </div>
        <div>
          <span class="field-label">保留已通过资源</span>
          <strong>{{ taskStore.latestPreservedResourceCount }} 个</strong>
        </div>
      </div>
    </div>

    <div class="panel">
      <h2 class="panel-title">Agent 职责分工</h2>
      <div class="flow-grid">
        <div v-for="agent in agents" :key="agent.name" class="agent-card">
          <span class="status-dot" :class="{ 'is-active': activeStep === agent.step }" />
          <strong>{{ agent.name }}</strong>
          <p>{{ agent.role }}</p>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { subscribeTaskEvents } from '@/api/client'
import { createGenerationTask } from '@/api/generation'
import AgentFlowView from '@/components/AgentFlow/AgentFlowView.vue'
import { useTaskStore } from '@/stores/taskStore'
import type { AgentStatusEvent } from '@/types/api'

const taskStore = useTaskStore()
const router = useRouter()
const starting = ref(false)
let source: EventSource | null = null
const terminalStatuses = new Set(['completed', 'failed', 'revision_required'])

const activeStep = computed(() => {
  const latestAgentEvent = [...taskStore.events].reverse().find((event) => event.step !== 'task')
  return latestAgentEvent?.step
})

const hasRevisionLoop = computed(
  () =>
    taskStore.events.some((event) => event.is_revision_round) ||
    taskStore.latestDecision === 'revision_required',
)

const canViewCurrentResources = computed(() => {
  return Boolean(
    taskStore.currentTaskId &&
      taskStore.events.some(
        (event) => event.step === 'task' && event.status === 'completed',
      ),
  )
})

const agents = [
  { step: 'load_profile', name: 'Profile Analysis Agent', role: '读取诊断画像，确定能力层级、薄弱知识点和学习目标。' },
  { step: 'retrieve_knowledge', name: 'Knowledge Retrieval Agent', role: '从知识库和向量库召回可追溯知识来源。' },
  { step: 'generate_resource', name: 'Content Generation Agent', role: '生成讲义、实训指导和分级测验。' },
  { step: 'review_resource', name: 'Review and Validation Agent', role: '检查事实准确、来源可追溯、难度匹配和覆盖度。' },
  { step: 'decide_next_step', name: 'Orchestrator Agent', role: '根据审核结果决定通过、修订、失败或人工复核。' },
]

function stepLabel(step: string) {
  return (
    {
      load_profile: '加载学习画像',
      retrieve_knowledge: '检索领域知识',
      generate_resource: '生成学习资源',
      review_resource: '审核与校验',
      decide_next_step: '协同决策',
      persist_resource: '资源入库',
      task: '任务状态',
    }[step] ?? step
  )
}

function stepDescription(step: string) {
  return (
    {
      load_profile: '读取学习者画像和诊断结果。',
      retrieve_knowledge: '召回知识点、来源和相关上下文。',
      generate_resource: '生成 lecture、practice_guide、graded_quiz。',
      review_resource: '执行事实、溯源、难度和覆盖检查。',
      decide_next_step: '判断是否通过、修订或进入人工复核。',
      persist_resource: '保存可展示资源并生成后续反馈入口。',
      task: '生成任务状态已更新。',
    }[step] ?? '任务事件已更新。'
  )
}

function statusLabel(status: string) {
  return (
    {
      completed: '已完成',
      running: '运行中',
      failed: '失败',
      pending: '等待中',
      revision_required: '需要修订',
    }[status] ?? status
  )
}

function decisionLabel(decision: string) {
  return (
    {
      pending: '等待中',
      passed: '已通过',
      failed: '未通过',
      revision_required: '需要修订',
    }[decision] ?? decision
  )
}

function strategyLabel(strategy: string) {
  return (
    {
      remedial: '补救讲解',
      consolidation: '巩固练习',
      challenge: '挑战任务',
      pending: '等待中',
    }[strategy] ?? strategy
  )
}

function resourceTypesText(resourceTypes: string[]) {
  const labels: Record<string, string> = {
    lecture: '讲义',
    practice_guide: '实训指导',
    graded_quiz: '分级测验',
  }
  return resourceTypes.map((type) => labels[type] ?? type).join('、')
}

function listText(values: string[]) {
  return values.join('、')
}

function timelineType(status: string) {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'revision_required') return 'warning'
  return 'primary'
}

function eventTimestamp(event: AgentStatusEvent) {
  const prefix = statusLabel(event.status)
  if (!event.timestamp) return prefix
  return `${prefix} · ${new Date(event.timestamp).toLocaleTimeString()}`
}

function payloadNumber(event: AgentStatusEvent, key: string) {
  const value = event.payload?.[key]
  return typeof value === 'number' ? value : null
}

function payloadString(event: AgentStatusEvent, key: string) {
  const value = event.payload?.[key]
  return typeof value === 'string' ? value : null
}

function payloadArrayLength(event: AgentStatusEvent, key: string) {
  const value = event.payload?.[key]
  return Array.isArray(value) ? value.length : null
}

function payloadSummary(event: AgentStatusEvent) {
  const facts: string[] = []
  if (event.step === 'load_profile') {
    const profileType = payloadString(event, 'profile_type')
    const weakCount = payloadNumber(event, 'weak_knowledge_count')
    if (profileType) facts.push(`画像：${profileType}`)
    if (weakCount !== null) facts.push(`薄弱点：${weakCount}`)
  }
  if (event.step === 'retrieve_knowledge') {
    const retrieved = payloadArrayLength(event, 'retrieved')
    const priority = payloadNumber(event, 'matched_priority_count')
    const prerequisite = payloadNumber(event, 'matched_prerequisite_count')
    if (retrieved !== null) facts.push(`来源：${retrieved}`)
    if (priority !== null) facts.push(`重点命中：${priority}`)
    if (prerequisite !== null) facts.push(`前置命中：${prerequisite}`)
  }
  if (event.step === 'generate_resource') {
    const resourceCount = payloadNumber(event, 'resource_count')
    const preserved = payloadNumber(event, 'preserved_resource_count')
    if (resourceCount !== null) facts.push(`资源：${resourceCount}`)
    if (preserved !== null) facts.push(`保留：${preserved}`)
  }
  if (event.step === 'review_resource') {
    const averageScore = payloadNumber(event, 'average_score')
    const revisionCount = payloadNumber(event, 'revision_required_count')
    const failedCount = payloadNumber(event, 'failed_count')
    if (averageScore !== null) facts.push(`均分：${averageScore}`)
    if (revisionCount !== null) facts.push(`修订：${revisionCount}`)
    if (failedCount !== null) facts.push(`失败：${failedCount}`)
  }
  if (event.step === 'decide_next_step') {
    const decision = payloadString(event, 'decision')
    if (decision) facts.push(`决策：${decisionLabel(decision)}`)
    if (taskStore.latestRevisionTypes.length) {
      facts.push(`对象：${resourceTypesText(taskStore.latestRevisionTypes)}`)
    }
  }
  return facts
}

async function startDemo() {
  source?.close()
  starting.value = true
  try {
    const task = await createGenerationTask()
    taskStore.setTask(task.task_id)
    source = subscribeTaskEvents(task.task_id, (event) => {
      taskStore.addEvent(event)
      if (event.step === 'task' && terminalStatuses.has(event.status)) {
        source?.close()
        source = null
      }
    })
    ElMessage.success('协同流已启动，正在接收 Agent 状态事件。')
  } catch (error) {
    ElMessage.error('协同流启动失败，请确认后端服务已启动。')
  } finally {
    starting.value = false
  }
}

onBeforeUnmount(() => source?.close())
</script>

<style scoped>
.agent-page {
  gap: 18px;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}

.summary-item {
  display: grid;
  gap: 6px;
  min-width: 0;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-panel);
  padding: 13px 14px;
}

.summary-item span,
.field-label {
  color: var(--app-muted);
  font-size: 12px;
}

.summary-item strong,
.revision-grid strong {
  min-width: 0;
  overflow: hidden;
  color: var(--app-text);
  font-size: 15px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(340px, 0.65fr);
  gap: 16px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.graph-panel {
  min-width: 0;
}

.event-panel {
  min-width: 0;
}

.event-timeline {
  max-height: 410px;
  overflow: auto;
  padding-right: 6px;
}

.event-row {
  display: grid;
  gap: 5px;
}

.event-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.event-title strong {
  color: var(--app-text);
}

.event-row p {
  margin: 0;
  color: var(--app-muted);
  font-size: 13px;
  line-height: 1.55;
}

.event-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.event-facts span {
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: var(--app-panel-soft);
  padding: 2px 8px;
  color: #344054;
  font-size: 12px;
  line-height: 1.6;
}

.revision-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.revision-grid > div {
  display: grid;
  gap: 7px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-panel-soft);
  padding: 13px;
}

.agent-card {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 10px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-panel-soft);
  padding: 14px;
}

.agent-card p {
  grid-column: 2;
  margin: 0;
  color: var(--app-muted);
  font-size: 13px;
  line-height: 1.6;
}

@media (max-width: 1180px) {
  .summary-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 1060px) {
  .agent-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .summary-strip,
  .revision-grid {
    grid-template-columns: 1fr;
  }
}
</style>
