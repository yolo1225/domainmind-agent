<template>
  <section class="page resource-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">学习资源</h1>
        <p class="page-subtitle">
          查看通过审核的讲义、实训指导和分级测验。学习者反馈会触发辅导 Agent，并推动画像和学习路径更新。
        </p>
      </div>
      <div class="toolbar">
        <el-button :loading="loading" @click="load">刷新资源</el-button>
        <el-button type="primary" @click="router.push('/agents')">生成新资源</el-button>
      </div>
    </div>

    <div v-if="!resources.length && !loading" class="empty-hint">
      <strong>还没有学习资源</strong>
      <p>请先完成诊断测评，或在 Agent 协作页启动一次生成流程。</p>
    </div>

    <div v-else class="resource-layout">
      <aside class="panel resource-list">
        <h2 class="panel-title">资源列表</h2>
        <button
          v-for="resource in resources"
          :key="resource.resource_id"
          class="resource-tab"
          :class="{ 'is-active': selected?.resource_id === resource.resource_id }"
          type="button"
          @click="selected = resource"
        >
          <span>{{ typeLabel(resource.resource_type) }}</span>
          <strong>{{ resource.title }}</strong>
          <small>难度 {{ resource.difficulty }} · {{ reviewLabel(resource.review_status) }}</small>
        </button>
      </aside>

      <main v-if="selected" class="panel resource-detail">
        <div class="resource-head">
          <div>
            <h2>{{ selected.title }}</h2>
            <p class="muted">{{ typeLabel(selected.resource_type) }} · 难度 {{ selected.difficulty }}</p>
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
            <el-button @click="sendFeedback(selected.resource_id, 'too_easy')">太简单，给挑战任务</el-button>
            <el-button @click="sendFeedback(selected.resource_id, 'too_hard')">太难，补救解释</el-button>
            <el-button @click="sendFeedback(selected.resource_id, 'confusing')">看不懂，重新讲解</el-button>
            <el-button type="warning" @click="sendFeedback(selected.resource_id, 'incorrect')">
              有错误，触发修订
            </el-button>
          </div>
        </section>
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
import { useRouter } from 'vue-router'
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

const router = useRouter()
const resources = ref<ResourceSummary[]>([])
const selected = ref<ResourceSummary | null>(null)
const loading = ref(false)
const lastFeedback = ref<FeedbackResult | null>(null)

const selectedId = computed(() => selected.value?.resource_id)

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
  return status === 'passed' ? '审核通过' : status
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

async function load() {
  loading.value = true
  try {
    resources.value = await listResources()
    selected.value =
      resources.value.find((resource) => resource.resource_id === selectedId.value) ??
      resources.value[0] ??
      null
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

watch(resources, (next) => {
  if (!selected.value && next.length) selected.value = next[0]
})

onMounted(load)
</script>

<style scoped>
.resource-page {
  gap: 18px;
}

.resource-layout {
  display: grid;
  grid-template-columns: 330px minmax(0, 1fr);
  gap: 16px;
}

.resource-list {
  align-self: start;
  display: grid;
  gap: 10px;
}

.resource-tab {
  display: grid;
  gap: 5px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-panel-soft);
  padding: 12px;
  color: var(--app-text);
  text-align: left;
  cursor: pointer;
}

.resource-tab.is-active {
  border-color: #9bb8f5;
  background: var(--app-accent-soft);
}

.resource-tab span,
.resource-tab small {
  color: var(--app-muted);
  font-size: 12px;
}

.resource-detail {
  display: grid;
  gap: 20px;
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
</style>
