<template>
  <section class="page diagnostic-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">诊断测评</h1>
        <p class="page-subtitle">
          从真实题库抽取题目，形成学习画像、薄弱知识点和学习路径，再把画像传给多智能体生成流程。
        </p>
      </div>
      <div class="toolbar">
        <el-select
          v-model="selectedLearnerId"
          class="learner-select"
          @change="changeLearner"
        >
          <el-option
            v-for="learner in learnerOptions"
            :key="learner.learner_id"
            :label="learner.learner_id"
            :value="learner.learner_id"
          />
        </el-select>
        <el-button :loading="loadingSession" @click="createSession">创建 10 题测评</el-button>
        <el-button v-if="session" @click="fillDemoAnswers">填入演示答案</el-button>
      </div>
    </div>

    <div class="panel">
      <el-steps :active="currentStep" finish-status="success" simple>
        <el-step title="创建测评" />
        <el-step title="提交答案" />
        <el-step title="生成画像" />
        <el-step title="生成资源" />
      </el-steps>
    </div>

    <div v-if="session" class="panel session-panel">
      <el-descriptions :column="3" border>
        <el-descriptions-item label="测评会话">{{ session.session_id }}</el-descriptions-item>
        <el-descriptions-item label="学习者">{{ session.learner_id }}</el-descriptions-item>
        <el-descriptions-item label="题目数量">{{ session.question_count }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <div v-if="session" class="panel question-panel">
      <article v-for="(question, index) in session.questions" :key="question.question_id" class="question-item">
        <div class="question-title">
          <strong>{{ index + 1 }}. {{ question.stem }}</strong>
          <el-tag size="small" effect="plain">难度 {{ question.difficulty }}</el-tag>
        </div>
        <el-radio-group
          v-if="question.question_type === 'single_choice'"
          v-model="answers[question.question_id]"
        >
          <el-radio
            v-for="(option, optionIndex) in question.options"
            :key="`${question.question_id}-${optionIndex}`"
            :label="optionIndex"
          >
            {{ option }}
          </el-radio>
        </el-radio-group>
        <el-input
          v-else
          v-model="answers[question.question_id]"
          type="textarea"
          :rows="3"
          placeholder="输入简答题答案"
        />
      </article>
      <div class="submit-row">
        <el-button type="primary" :loading="loadingSubmit" @click="submitSession">
          提交诊断并生成画像
        </el-button>
      </div>
    </div>

    <div v-else class="empty-hint">
      <strong>先创建一组诊断题</strong>
      <p>系统会从 ai_app_dev 领域题库读取题目，用答题结果生成差异化学习画像。</p>
    </div>

    <div v-if="result" class="panel result-panel">
      <div class="result-header">
        <div>
          <h2 class="panel-title">诊断结果</h2>
          <p class="page-subtitle">
            画像类型为 {{ profileLabel(result.profile_type) }}，得分 {{ result.score }}，下一步可以启动资源生成。
          </p>
        </div>
        <el-button type="primary" :loading="loadingGeneration" @click="generateResources">
          启动资源生成
        </el-button>
      </div>

      <div class="result-grid">
        <div class="metric-card">
          <span class="metric-label">正确题数</span>
          <div class="metric-value">{{ result.correct_count }}/{{ result.question_count }}</div>
        </div>
        <div class="metric-card">
          <span class="metric-label">画像 ID</span>
          <strong>{{ result.profile_id }}</strong>
        </div>
        <div class="metric-card">
          <span class="metric-label">学习路径 ID</span>
          <strong>{{ result.learning_path_id }}</strong>
        </div>
      </div>

      <div class="weak-block">
        <h3>薄弱知识点</h3>
        <div class="tag-list">
          <el-tag
            v-for="item in result.weak_knowledge"
            :key="item.knowledge_id"
            type="warning"
            effect="plain"
          >
            {{ item.name }}
          </el-tag>
        </div>
      </div>
    </div>

    <div v-if="generation" class="panel">
      <h2 class="panel-title">生成结果</h2>
      <el-steps :active="(generation.agent_trace ?? []).length" finish-status="success" simple>
        <el-step v-for="trace in generation.agent_trace ?? []" :key="trace.agent_name" :title="agentLabel(trace.agent_name)" />
      </el-steps>
      <el-alert class="resource-alert" type="success" show-icon>
        <template #title>
          已生成 {{ generation.resources.length }} 类学习资源，协同决策为 {{ generation.decision }}。请进入“学习资源”页查看内容并提交反馈。
        </template>
      </el-alert>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'

import {
  createDiagnosticSession,
  submitDiagnosticSession,
  type DiagnosticResult,
  type DiagnosticSession,
} from '@/api/diagnostics'
import { createGenerationTask, type GenerationTaskResult } from '@/api/generation'
import { listLearners, type LearnerSummary } from '@/api/learners'
import { useLearnerStore } from '@/stores/learnerStore'

const route = useRoute()
const learnerStore = useLearnerStore()
const selectedLearnerId = ref(learnerStore.selectedLearnerId)
const learnerOptions = ref<LearnerSummary[]>([])
const session = ref<DiagnosticSession | null>(null)
const result = ref<DiagnosticResult | null>(null)
const generation = ref<GenerationTaskResult | null>(null)
const answers = ref<Record<string, string | number>>({})
const loadingSession = ref(false)
const loadingSubmit = ref(false)
const loadingGeneration = ref(false)

const currentStep = computed(() => {
  if (generation.value) return 4
  if (result.value) return 3
  if (session.value) return 1
  return 0
})

const learnerId = computed(() => {
  return selectedLearnerId.value || learnerStore.selectedLearnerId
})

watch(
  () => route.query.learner_id,
  (raw) => {
    if (typeof raw === 'string' && raw.trim()) {
      selectedLearnerId.value = raw
      learnerStore.setSelectedLearner(raw)
    }
  },
  { immediate: true },
)

async function loadLearnerOptions() {
  try {
    learnerOptions.value = await listLearners()
    if (!learnerOptions.value.some((learner) => learner.learner_id === selectedLearnerId.value)) {
      selectedLearnerId.value = learnerOptions.value[0]?.learner_id ?? learnerStore.selectedLearnerId
      learnerStore.setSelectedLearner(selectedLearnerId.value)
    }
  } catch (error) {
    learnerOptions.value = [{ learner_id: selectedLearnerId.value, profile_type: '', target_domain: 'ai_app_dev', ability_level: 0, profile_status: 'not_started' }]
  }
}

function changeLearner(learnerId: string) {
  selectedLearnerId.value = learnerId
  learnerStore.setSelectedLearner(learnerId)
  session.value = null
  result.value = null
  generation.value = null
  answers.value = {}
}

function profileLabel(profileType: string) {
  return (
    {
      beginner: '基础补齐型',
      intermediate: '能力提升型',
      advanced: '挑战拓展型',
    }[profileType] ?? profileType
  )
}

function agentLabel(agentName: string) {
  return (
    {
      profile_analysis_agent: '画像分析',
      knowledge_retrieval_agent: '知识检索',
      content_generation_agent: '内容生成',
      review_validation_agent: '审核校验',
      orchestrator_agent: '协同决策',
    }[agentName] ?? agentName
  )
}

async function createSession() {
  loadingSession.value = true
  try {
    learnerStore.setSelectedLearner(learnerId.value)
    session.value = await createDiagnosticSession(learnerId.value)
    result.value = null
    generation.value = null
    answers.value = {}
  } catch (error) {
    ElMessage.error('创建诊断测评失败，请确认后端服务已启动。')
  } finally {
    loadingSession.value = false
  }
}

function fillDemoAnswers() {
  if (!session.value) return
  const nextAnswers: Record<string, string | number> = {}
  session.value.questions.forEach((question, index) => {
    nextAnswers[question.question_id] =
      question.question_type === 'single_choice'
        ? index % 4 === 0
          ? 1
          : 0
        : '语义完整性、召回精度、上下文占用、可追溯来源'
  })
  answers.value = nextAnswers
}

async function submitSession() {
  if (!session.value) return
  const payload = session.value.questions.map((question) => ({
    question_id: question.question_id,
    answer: answers.value[question.question_id] ?? '',
  }))
  loadingSubmit.value = true
  try {
    result.value = await submitDiagnosticSession(session.value.session_id, payload, session.value.learner_id)
    learnerStore.setSelectedLearner(result.value.learner_id)
    ElMessage.success('诊断完成，学习画像已生成。')
  } catch (error) {
    ElMessage.error('提交诊断失败，请检查答案或后端服务。')
  } finally {
    loadingSubmit.value = false
  }
}

async function generateResources() {
  if (!result.value) return
  loadingGeneration.value = true
  try {
    generation.value = await createGenerationTask(result.value.profile_id, result.value.learner_id)
    ElMessage.success('学习资源生成完成。')
  } catch (error) {
    ElMessage.error('生成资源失败，请确认生成接口可用。')
  } finally {
    loadingGeneration.value = false
  }
}

onMounted(loadLearnerOptions)
</script>

<style scoped>
.diagnostic-page {
  gap: 18px;
}

.session-panel {
  background: #fbfdff;
}

.learner-select {
  width: 160px;
}

.question-panel {
  display: grid;
  gap: 14px;
}

.question-item {
  display: grid;
  gap: 10px;
  border-bottom: 1px solid var(--app-border);
  padding-bottom: 14px;
}

.question-item:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.question-title,
.submit-row,
.result-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.question-title strong {
  line-height: 1.65;
}

.submit-row {
  justify-content: flex-end;
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.metric-card strong {
  display: block;
  margin-top: 10px;
  overflow-wrap: anywhere;
}

.weak-block {
  margin-top: 18px;
}

.weak-block h3 {
  margin: 0 0 10px;
  font-size: 15px;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.resource-alert {
  margin-top: 14px;
}

@media (max-width: 760px) {
  .question-title,
  .result-header {
    display: grid;
  }

  .result-grid {
    grid-template-columns: 1fr;
  }
}
</style>
