<template>
  <section class="page agent-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Agent 协作工作台</h1>
        <p class="page-subtitle">
          这里展示多智能体不是一次模型调用，而是画像、检索、生成、审核、决策各节点可追踪流转。
        </p>
      </div>
      <el-button type="primary" :loading="starting" @click="startDemo">启动协同流</el-button>
    </div>

    <div class="agent-grid">
      <div class="panel graph-panel">
        <div class="section-head">
          <h2 class="panel-title">工作流拓扑</h2>
          <el-tag v-if="taskStore.currentTaskId" effect="plain">{{ taskStore.currentTaskId }}</el-tag>
        </div>
        <AgentFlowView :active-step="activeStep" />
      </div>

      <div class="panel">
        <h2 class="panel-title">实时事件</h2>
        <el-timeline v-if="taskStore.events.length">
          <el-timeline-item
            v-for="(event, index) in taskStore.events"
            :key="`${event.step}-${index}`"
            :type="event.status === 'completed' ? 'success' : 'primary'"
            :timestamp="statusLabel(event.status)"
          >
            <strong>{{ stepLabel(event.step) }}</strong>
            <p>{{ stepDescription(event.step) }}</p>
          </el-timeline-item>
        </el-timeline>
        <div v-else class="empty-hint">
          <strong>等待任务启动</strong>
          <p>点击“启动协同流”，前端会订阅 SSE 事件并同步更新流程图。</p>
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
import { ElMessage } from 'element-plus'

import { subscribeTaskEvents } from '@/api/client'
import { createGenerationTask } from '@/api/generation'
import AgentFlowView from '@/components/AgentFlow/AgentFlowView.vue'
import { useTaskStore } from '@/stores/taskStore'

const taskStore = useTaskStore()
const starting = ref(false)
let source: EventSource | null = null

const activeStep = computed(() => taskStore.events[taskStore.events.length - 1]?.step)

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
    }[status] ?? status
  )
}

async function startDemo() {
  source?.close()
  starting.value = true
  try {
    const task = await createGenerationTask()
    taskStore.setTask(task.task_id)
    source = subscribeTaskEvents(task.task_id, (event) => {
      taskStore.addEvent(event.step, event.status)
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

.agent-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr);
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

:deep(.el-timeline-item__content p) {
  margin: 4px 0 0;
  color: var(--app-muted);
  line-height: 1.55;
}

@media (max-width: 1060px) {
  .agent-grid {
    grid-template-columns: 1fr;
  }
}
</style>
