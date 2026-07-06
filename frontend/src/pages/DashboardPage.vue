<template>
  <section class="page dashboard-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">演示工作台</h1>
        <p class="page-subtitle">
          按照比赛 MVP 闭环组织演示：学习者画像、诊断、知识检索、资源生成、双路审核、协同决策、反馈更新。
        </p>
      </div>
      <div class="toolbar">
        <el-button @click="router.push('/diagnostics')">开始诊断</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreateTask">
          直接生成资源
        </el-button>
      </div>
    </div>

    <div class="metric-grid">
      <div v-for="metric in metrics" :key="metric.label" class="metric-card">
        <span class="metric-label">{{ metric.label }}</span>
        <div class="metric-value">{{ metric.value }}</div>
        <p>{{ metric.note }}</p>
      </div>
    </div>

    <div class="panel demo-strip">
      <div>
        <h2 class="panel-title">一条可点击的完整演示线</h2>
        <p class="page-subtitle">
          先跑诊断，再看 Agent 协作流，最后进入资源反馈和学习报告。后端还在补真逻辑时，前端先把产品路径稳定下来。
        </p>
      </div>
      <div class="flow-grid">
        <button
          v-for="(step, index) in demoSteps"
          :key="step.path"
          class="step-card"
          type="button"
          @click="router.push(step.path)"
        >
          <span class="step-index">{{ index + 1 }}</span>
          <strong>{{ step.title }}</strong>
          <small>{{ step.description }}</small>
        </button>
      </div>
    </div>

    <div class="dashboard-grid">
      <div class="panel">
        <div class="section-head">
          <h2 class="panel-title">最近生成任务</h2>
          <el-button text @click="router.push('/agents')">查看协作过程</el-button>
        </div>
        <el-table v-if="tasks.length" :data="tasks" size="large">
          <el-table-column prop="task_id" label="任务 ID" min-width="180" />
          <el-table-column prop="status" label="状态" width="120" />
          <el-table-column prop="decision" label="决策" width="120" />
        </el-table>
        <div v-else class="empty-hint">
          <strong>还没有生成任务</strong>
          <p>点击“开始诊断”完成测评，或直接生成一组演示资源。</p>
        </div>
      </div>

      <div class="panel">
        <h2 class="panel-title">评委会看到什么</h2>
        <ul class="proof-list">
          <li>每个 Agent 有职责、状态和运行记录。</li>
          <li>每份资源都展示知识来源和审核状态。</li>
          <li>反馈会触发辅导动作，并标记学习路径刷新。</li>
          <li>指标页对应离线 test_script 的验收目标。</li>
        </ul>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { createGenerationTask, getGenerationTask } from '@/api/generation'

const router = useRouter()
const creating = ref(false)
const tasks = ref<Array<{ task_id: string; status: string; decision?: string }>>([])

const metrics = [
  { label: '领域包', value: '1', note: 'ai_app_dev 主验证领域' },
  { label: '知识点目标', value: '50+', note: '支撑检索和溯源' },
  { label: '诊断题目标', value: '60+', note: '覆盖画像分层' },
  { label: '评测样例', value: '50', note: '离线脚本可复现' },
]

const demoSteps = [
  { title: '诊断测评', description: '答题后生成画像和薄弱知识点', path: '/diagnostics' },
  { title: 'Agent 协作', description: '观察检索、生成、审核、决策流转', path: '/agents' },
  { title: '学习资源', description: '查看讲义、实训指导和测验', path: '/resources' },
  { title: '学习报告', description: '看雷达图、路径和反馈刷新状态', path: '/reports' },
  { title: '评测指标', description: '对齐幻觉率、难度匹配和覆盖率', path: '/metrics' },
]

async function handleCreateTask() {
  creating.value = true
  try {
    const created = await createGenerationTask()
    const task = await getGenerationTask(created.task_id)
    tasks.value.unshift(task)
    ElMessage.success('资源生成任务已完成，可以进入学习资源页查看。')
  } catch (error) {
    ElMessage.error('生成任务创建失败，请确认后端服务已启动。')
  } finally {
    creating.value = false
  }
}
</script>

<style scoped>
.dashboard-page {
  gap: 20px;
}

.metric-card p {
  margin: 8px 0 0;
  color: var(--app-muted);
  font-size: 13px;
  line-height: 1.5;
}

.demo-strip {
  display: grid;
  gap: 16px;
}

.step-card {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 10px;
  min-height: 108px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-panel-soft);
  padding: 14px;
  color: var(--app-text);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 180ms ease,
    background 180ms ease,
    transform 180ms ease;
}

.step-card:hover {
  border-color: #9bb8f5;
  background: #fff;
  transform: translateY(-1px);
}

.step-index {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  background: var(--app-accent-soft);
  color: var(--app-accent);
  font-weight: 750;
}

.step-card strong {
  align-self: center;
}

.step-card small {
  grid-column: 2;
  color: var(--app-muted);
  line-height: 1.5;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.8fr);
  gap: 16px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.empty-hint p,
.proof-list {
  margin: 8px 0 0;
  color: var(--app-muted);
  line-height: 1.7;
}

.proof-list {
  padding-left: 20px;
}

@media (max-width: 980px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}
</style>
