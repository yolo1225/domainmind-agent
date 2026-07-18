<template>
  <section class="page learner-profile-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">学情画像</h1>
        <p class="page-subtitle">
          从诊断答题记录生成学习者能力画像，定位薄弱知识点，并把画像结果传递给个性化资源生成流程。
        </p>
      </div>
      <div class="toolbar">
        <el-button :loading="loadingLearners" @click="loadLearners">刷新画像</el-button>
        <el-button @click="openCreateDialog">新增学习者</el-button>
        <el-button type="primary" @click="goDiagnostics">创建诊断测评</el-button>
      </div>
    </div>

    <div class="profile-workspace">
      <aside class="panel learner-list-panel">
        <div class="section-head">
          <h2 class="panel-title">学习者</h2>
          <el-tag effect="plain">{{ learners.length }} 人</el-tag>
        </div>

        <el-skeleton v-if="loadingLearners" :rows="5" animated />
        <el-empty v-else-if="learners.length === 0" description="暂无学习者数据" />
        <div v-else class="learner-list">
          <button
            v-for="learner in learners"
            :key="learner.learner_id"
            class="learner-row"
            :class="{ 'is-active': learner.learner_id === selectedLearnerId }"
            type="button"
            @click="selectLearner(learner.learner_id)"
          >
            <span>
              <strong>{{ learner.learner_id }}</strong>
              <small>{{ learner.target_domain }}</small>
            </span>
            <span class="learner-meta">
              <el-tag
                size="small"
                :type="learner.profile_status === 'ready' ? 'success' : 'info'"
                effect="plain"
              >
                {{ statusLabel(learner.profile_status) }}
              </el-tag>
              <b v-if="learner.ability_level">{{ learner.ability_level }} 级</b>
            </span>
          </button>
        </div>
      </aside>

      <main class="profile-detail">
        <el-skeleton v-if="loadingProfile" class="panel" :rows="9" animated />
        <el-alert
          v-else-if="errorMessage"
          class="panel"
          type="error"
          show-icon
          :title="errorMessage"
        />
        <template v-else-if="profile">
          <section class="panel profile-summary-panel">
            <div class="profile-summary">
              <div>
                <h2>{{ profile.learner_id }}</h2>
                <p>
                  {{ profile.background || '未填写学习背景' }}，{{ styleLabel(profile.learning_style) }}，
                  {{ profile.experience_years }} 年相关经验
                </p>
              </div>
              <div class="summary-actions">
                <el-tag :type="profile.profile_status === 'ready' ? 'success' : 'info'" effect="plain">
                  {{ profileLabel(profile.profile_type) }}
                </el-tag>
                <el-button
                  type="primary"
                  :disabled="profile.profile_status !== 'ready'"
                  :loading="generating"
                  @click="generateResources"
                >
                  生成个性化资源
                </el-button>
              </div>
            </div>

            <div class="stat-strip">
              <div>
                <span>诊断正确率</span>
                <strong>{{ profile.diagnostic_summary.accuracy }}%</strong>
              </div>
              <div>
                <span>答题记录</span>
                <strong>
                  {{ profile.diagnostic_summary.correct_count }}/{{ profile.diagnostic_summary.answer_count }}
                </strong>
              </div>
              <div>
                <span>画像 ID</span>
                <strong>{{ profile.profile_id || '待生成' }}</strong>
              </div>
            </div>
            <el-alert
              v-if="profileGenerationTask"
              class="profile-generation-alert"
              type="info"
              show-icon
              :title="`资源生成任务 ${profileGenerationTask.task_id} 已启动，状态：${profileGenerationTask.status}`"
            >
              <template #default>
                <div class="generation-actions">
                  <el-button @click="router.push({ path: '/agents', query: { task_id: profileGenerationTask.task_id } })">
                    查看协同进度
                  </el-button>
                  <el-button
                    v-if="profileGenerationTask.status === 'completed'"
                    type="primary"
                    @click="router.push({ path: '/resources', query: { task_id: profileGenerationTask.task_id } })"
                  >
                    查看本次资源
                  </el-button>
                </div>
              </template>
            </el-alert>
          </section>

          <section v-if="profile.profile_status !== 'ready'" class="empty-hint">
            <strong>尚未生成学情画像</strong>
            <p>请先完成诊断测评，系统会根据答题记录生成五维能力画像、薄弱知识点和学习路径。</p>
            <el-button type="primary" @click="goDiagnostics">开始诊断测评</el-button>
          </section>

          <template v-else>
            <div class="profile-grid">
              <section class="panel">
                <div class="section-head">
                  <h2 class="panel-title">五维能力雷达</h2>
                  <el-tag effect="plain">平均 {{ averageRadar }} 分</el-tag>
                </div>
                <RadarChart :values="profile.radar" />
              </section>

              <section class="panel">
                <h2 class="panel-title">分类掌握度</h2>
                <div v-if="categoryRows.length" class="mastery-list">
                  <div v-for="item in categoryRows" :key="item.name" class="mastery-row">
                    <div>
                      <span>{{ item.name }}</span>
                      <strong>{{ item.value }}%</strong>
                    </div>
                    <el-progress :percentage="item.value" :stroke-width="10" />
                  </div>
                </div>
                <div v-else class="empty-hint small">
                  <strong>暂无分类掌握度</strong>
                  <p>完成诊断后会按知识分类聚合掌握情况。</p>
                </div>
              </section>
            </div>

            <section class="panel">
              <div class="section-head">
                <h2 class="panel-title">薄弱知识点</h2>
                <el-tag type="warning" effect="plain">{{ profile.weak_knowledge.length }} 项</el-tag>
              </div>
              <el-table v-if="profile.weak_knowledge.length" :data="profile.weak_knowledge">
                <el-table-column prop="name" label="知识点" min-width="180" />
                <el-table-column prop="category" label="分类" min-width="120" />
                <el-table-column label="薄弱等级" width="120">
                  <template #default="{ row }">
                    <el-rate
                      :model-value="row.weakness_level"
                      disabled
                      :max="5"
                      size="small"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="原因" min-width="150">
                  <template #default="{ row }">{{ weaknessLabel(row.weakness_type) }}</template>
                </el-table-column>
                <el-table-column label="建议动作" min-width="120">
                  <template #default="{ row }">
                    <el-tag type="warning" effect="plain">{{ row.suggested_action || '巩固练习' }}</el-tag>
                  </template>
                </el-table-column>
              </el-table>
              <div v-else class="empty-hint small">
                <strong>暂无明显薄弱点</strong>
                <p>当前诊断未发现低分知识点，可直接生成进阶资源。</p>
              </div>
            </section>

            <section class="panel">
              <div class="section-head">
                <h2 class="panel-title">推荐学习路径</h2>
                <el-tag type="success" effect="plain">可随反馈刷新</el-tag>
              </div>
              <el-steps
                v-if="pathStages.length"
                :active="pathStages.length"
                finish-status="success"
                align-center
              >
                <el-step
                  v-for="stage in pathStages"
                  :key="stage.name"
                  :title="stage.name"
                  :description="stage.description"
                />
              </el-steps>
              <div v-else class="empty-hint small">
                <strong>暂无学习路径</strong>
                <p>完成诊断后会自动生成从前置知识到反馈更新的学习路径。</p>
              </div>
            </section>
          </template>
        </template>
      </main>
    </div>

    <el-dialog
      v-model="createDialogVisible"
      title="新增学习者"
      width="520px"
      destroy-on-close
    >
      <el-form label-position="top" @submit.prevent>
        <div class="create-form-grid">
          <el-form-item label="学习者代号" required>
            <el-input
              v-model="createForm.learner_id"
              maxlength="64"
              placeholder="例如 learner_004"
            />
          </el-form-item>
          <el-form-item label="相关经验年限" required>
            <el-input-number
              v-model="createForm.experience_years"
              :min="0"
              :max="50"
              controls-position="right"
            />
          </el-form-item>
        </div>
        <div class="create-form-grid">
          <el-form-item label="目标领域" required>
            <el-select
              v-model="createForm.target_domain"
              :loading="loadingDomains"
              placeholder="请选择目标领域"
            >
              <el-option
                v-for="domain in domainOptions"
                :key="domain.domain_code"
                :label="`${domain.name}（${domain.domain_code}）`"
                :value="domain.domain_code"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="学习风格" required>
            <el-select v-model="createForm.learning_style">
              <el-option label="理论优先" value="theory" />
              <el-option label="实操优先" value="practice" />
              <el-option label="混合型" value="mixed" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="学习背景">
          <el-input
            v-model="createForm.background"
            type="textarea"
            :rows="3"
            maxlength="255"
            show-word-limit
            placeholder="简要描述基础、目标和已有项目经验"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="createDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="creatingLearner" @click="submitCreateLearner">
            创建学习者
          </el-button>
        </div>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { listDomains, type DomainSummary } from '@/api/domains'
import { createGenerationTask, getGenerationTask, type GenerationTaskResult } from '@/api/generation'
import {
  createLearner,
  getLearnerProfile,
  listLearners,
  type LearnerCreatePayload,
  type LearnerProfileDetail,
  type LearnerSummary,
} from '@/api/learners'
import RadarChart from '@/components/Charts/RadarChart.vue'
import { useLearnerStore } from '@/stores/learnerStore'

const router = useRouter()
const learnerStore = useLearnerStore()
const learners = ref<LearnerSummary[]>([])
const profile = ref<LearnerProfileDetail | null>(null)
const selectedLearnerId = ref(learnerStore.selectedLearnerId)
const loadingLearners = ref(false)
const loadingProfile = ref(false)
const generating = ref(false)
const profileGenerationTask = ref<GenerationTaskResult | null>(null)
let profileGenerationPollTimer: number | null = null
const creatingLearner = ref(false)
const createDialogVisible = ref(false)
const loadingDomains = ref(false)
const errorMessage = ref('')
const domainOptions = ref<DomainSummary[]>([
  { domain_code: 'ai_app_dev', name: '人工智能应用开发实训', status: 'active' },
])
const createForm = ref<LearnerCreatePayload>({
  learner_id: '',
  background: '',
  target_domain: 'ai_app_dev',
  experience_years: 0,
  learning_style: 'mixed',
})

const categoryRows = computed(() =>
  Object.entries(profile.value?.category_mastery ?? {}).map(([name, value]) => ({
    name,
    value: Math.round(Number(value)),
  })),
)

const pathStages = computed(() => profile.value?.learning_path?.stages ?? [])

const averageRadar = computed(() => {
  const values = profile.value?.radar ?? []
  if (!values.length) return 0
  return Math.round(values.reduce((total, value) => total + Number(value), 0) / values.length)
})

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

function statusLabel(status: string) {
  return status === 'ready' ? '已画像' : '待诊断'
}

function styleLabel(style: string) {
  return (
    {
      theory: '理论型',
      practice: '实操型',
      mixed: '混合型',
    }[style] ?? style
  )
}

function weaknessLabel(type?: string) {
  return (
    {
      not_mastered: '尚未掌握',
      partial_confusion: '部分混淆',
      needs_consolidation: '需要巩固',
    }[type ?? ''] ?? '诊断低分'
  )
}

async function loadDomainOptions() {
  loadingDomains.value = true
  try {
    const domains = await listDomains()
    if (domains.length) {
      domainOptions.value = domains
    }
  } catch (error) {
    domainOptions.value = [
      { domain_code: 'ai_app_dev', name: '人工智能应用开发实训', status: 'active' },
    ]
  } finally {
    loadingDomains.value = false
  }
}

function resetCreateForm() {
  const nextIndex = learners.value.length + 1
  const defaultDomain = domainOptions.value[0]?.domain_code ?? 'ai_app_dev'
  createForm.value = {
    learner_id: `learner_${String(nextIndex).padStart(3, '0')}`,
    background: '',
    target_domain: defaultDomain,
    experience_years: 0,
    learning_style: 'mixed',
  }
}

async function openCreateDialog() {
  await loadDomainOptions()
  resetCreateForm()
  createDialogVisible.value = true
}

function normalizeCreateForm(): LearnerCreatePayload {
  return {
    learner_id: createForm.value.learner_id.trim(),
    background: createForm.value.background.trim(),
    target_domain: createForm.value.target_domain,
    experience_years: Number(createForm.value.experience_years ?? 0),
    learning_style: createForm.value.learning_style,
  }
}

async function submitCreateLearner() {
  const payload = normalizeCreateForm()
  if (!/^[a-zA-Z0-9_-]{3,64}$/.test(payload.learner_id)) {
    ElMessage.warning('学习者代号需为 3-64 位字母、数字、下划线或短横线。')
    return
  }
  creatingLearner.value = true
  try {
    const created = await createLearner(payload)
    createDialogVisible.value = false
    ElMessage.success('学习者已创建，可继续发起诊断测评。')
    await loadLearners()
    await selectLearner(created.learner_id)
  } catch (error) {
    ElMessage.error('学习者创建失败，请检查代号是否重复。')
  } finally {
    creatingLearner.value = false
  }
}

async function loadLearners() {
  loadingLearners.value = true
  try {
    learners.value = await listLearners()
    if (!learners.value.some((learner) => learner.learner_id === selectedLearnerId.value)) {
      selectedLearnerId.value = learners.value[0]?.learner_id ?? 'learner_001'
    }
    learnerStore.setSelectedLearner(selectedLearnerId.value)
    await loadProfile(selectedLearnerId.value)
  } catch (error) {
    ElMessage.error('学习者列表加载失败，请确认后端服务已启动。')
  } finally {
    loadingLearners.value = false
  }
}

async function loadProfile(learnerId: string) {
  loadingProfile.value = true
  errorMessage.value = ''
  try {
    profile.value = await getLearnerProfile(learnerId)
  } catch (error) {
    profile.value = null
    errorMessage.value = '画像详情加载失败，请先完成诊断测评或检查后端服务。'
  } finally {
    loadingProfile.value = false
  }
}

async function selectLearner(learnerId: string) {
  selectedLearnerId.value = learnerId
  learnerStore.setSelectedLearner(learnerId)
  profileGenerationTask.value = null
  stopProfileGenerationPolling()
  await loadProfile(learnerId)
}

function goDiagnostics() {
  router.push({ path: '/diagnostics', query: { learner_id: selectedLearnerId.value } })
}

async function generateResources() {
  if (!profile.value?.profile_id) return
  generating.value = true
  try {
    const task = await createGenerationTask(profile.value.profile_id, profile.value.learner_id)
    ElMessage.success('资源生成任务已启动，当前页面将保留任务状态。')
    profileGenerationTask.value = task
    startProfileGenerationPolling(task.task_id)
  } catch (error) {
    ElMessage.error('资源生成失败，请确认生成服务可用。')
  } finally {
    generating.value = false
  }
}

function stopProfileGenerationPolling() {
  if (profileGenerationPollTimer !== null) {
    window.clearInterval(profileGenerationPollTimer)
    profileGenerationPollTimer = null
  }
}

function startProfileGenerationPolling(taskId: string) {
  stopProfileGenerationPolling()
  profileGenerationPollTimer = window.setInterval(async () => {
    try {
      const detail = await getGenerationTask(taskId)
      if (profileGenerationTask.value?.task_id !== taskId) return
      profileGenerationTask.value = { ...profileGenerationTask.value, ...detail }
      if (['completed', 'failed', 'waiting_human'].includes(detail.status)) {
        stopProfileGenerationPolling()
      }
    } catch {
      // Keep the task link available while the status endpoint is unavailable.
    }
  }, 2000)
}

onMounted(loadLearners)
onBeforeUnmount(stopProfileGenerationPolling)
</script>

<style scoped>
.learner-profile-page {
  gap: 18px;
}

.profile-workspace {
  display: grid;
  grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.learner-list-panel {
  position: sticky;
  top: 18px;
}

.section-head,
.profile-summary,
.summary-actions,
.stat-strip > div,
.mastery-row > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-head {
  margin-bottom: 12px;
}

.learner-list {
  display: grid;
  gap: 8px;
}

.learner-row {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-panel);
  padding: 12px;
  color: var(--app-text);
  cursor: pointer;
  text-align: left;
}

.learner-row:hover,
.learner-row.is-active {
  border-color: #93b4ef;
  background: var(--app-accent-soft);
}

.learner-row strong,
.learner-row small {
  display: block;
}

.learner-row small,
.learner-meta {
  color: var(--app-muted);
}

.learner-meta {
  display: grid;
  justify-items: end;
  gap: 6px;
}

.profile-detail {
  display: grid;
  gap: 16px;
}

.profile-summary-panel {
  display: grid;
  gap: 16px;
}

.profile-summary h2 {
  margin: 0;
  font-size: 22px;
  line-height: 1.25;
}

.profile-summary p {
  margin: 7px 0 0;
  color: var(--app-muted);
  line-height: 1.6;
}

.summary-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.profile-generation-alert {
  margin-top: 16px;
}

.generation-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 10px;
}

.stat-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.stat-strip > div {
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-panel-soft);
  padding: 12px;
}

.stat-strip span,
.mastery-row span {
  color: var(--app-muted);
}

.stat-strip strong {
  overflow-wrap: anywhere;
}

.profile-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
  gap: 16px;
}

.mastery-list {
  display: grid;
  gap: 14px;
}

.mastery-row {
  display: grid;
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

.create-form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(170px, 0.7fr);
  gap: 14px;
}

.create-form-grid :deep(.el-select),
.create-form-grid :deep(.el-input-number) {
  width: 100%;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 1100px) {
  .profile-workspace,
  .profile-grid {
    grid-template-columns: 1fr;
  }

  .learner-list-panel {
    position: static;
  }
}

@media (max-width: 760px) {
  .profile-summary,
  .section-head,
  .stat-strip > div,
  .mastery-row > div {
    display: grid;
    justify-content: stretch;
  }

  .summary-actions {
    justify-content: stretch;
  }

  .stat-strip {
    grid-template-columns: 1fr;
  }

  .create-form-grid {
    grid-template-columns: 1fr;
    gap: 0;
  }
}
</style>
