<template>
  <section class="page report-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">学习报告</h1>
        <p class="page-subtitle">
          汇总学习者画像、推荐路径和资源反馈后的刷新状态，用于展示个性化闭环的当前结果。
        </p>
      </div>
      <el-button :loading="loading" @click="load">加载 learner_001</el-button>
    </div>

    <div class="report-grid">
      <div class="panel">
        <div class="section-head">
          <h2 class="panel-title">能力雷达</h2>
          <el-tag v-if="report?.profile_type" effect="plain">{{ profileLabel(report.profile_type) }}</el-tag>
        </div>
        <RadarChart :values="report?.radar ?? [0, 0, 0, 0, 0]" />
      </div>

      <div class="panel">
        <h2 class="panel-title">质量指标</h2>
        <div v-if="report" class="quality-list">
          <div>
            <span>幻觉率</span>
            <strong>{{ percent(report.metrics.hallucination_rate) }}</strong>
          </div>
          <div>
            <span>难度匹配</span>
            <strong>{{ percent(report.metrics.difficulty_match) }}</strong>
          </div>
          <div>
            <span>知识覆盖</span>
            <strong>{{ percent(report.metrics.knowledge_coverage) }}</strong>
          </div>
        </div>
        <div v-else class="empty-hint">
          <strong>等待报告数据</strong>
          <p>完成诊断和资源生成后，这里会展示画像与评价指标。</p>
        </div>
      </div>
    </div>

    <div v-if="report" class="panel">
      <div class="section-head">
        <h2 class="panel-title">推荐学习路径</h2>
        <el-tag type="success" effect="plain">可随反馈刷新</el-tag>
      </div>
      <el-steps v-if="pathDetail.length" :active="pathDetail.length" finish-status="success">
        <el-step
          v-for="item in pathDetail"
          :key="item.name"
          :title="item.name"
          :description="item.description"
        />
      </el-steps>
      <el-steps v-else :active="report.path.length" finish-status="success">
        <el-step v-for="item in report.path" :key="item" :title="item" />
      </el-steps>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { getLearningReport, type LearningReport } from '@/api/reports'
import RadarChart from '@/components/Charts/RadarChart.vue'

const report = ref<LearningReport | null>(null)
const loading = ref(false)

const pathDetail = computed(() => report.value?.path_detail ?? [])

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

async function load() {
  loading.value = true
  try {
    report.value = await getLearningReport('learner_001')
  } catch (error) {
    ElMessage.error('学习报告加载失败，请先完成诊断或确认后端服务。')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.report-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.6fr);
  gap: 16px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.quality-list {
  display: grid;
  gap: 12px;
}

.quality-list div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-panel-soft);
  padding: 14px;
}

.quality-list span {
  color: var(--app-muted);
}

.quality-list strong {
  font-size: 24px;
}

@media (max-width: 900px) {
  .report-grid {
    grid-template-columns: 1fr;
  }

  .section-head {
    display: grid;
  }
}
</style>
