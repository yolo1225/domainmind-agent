<template>
  <section class="page metrics-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">评测指标</h1>
        <p class="page-subtitle">
          这里展示比赛 MVP 的可复现验收目标，最终数据应由 test_script 离线脚本产出，前端负责清晰呈现。
        </p>
      </div>
    </div>

    <div class="metric-grid">
      <div v-for="metric in metrics" :key="metric.label" class="metric-card">
        <span class="metric-label">{{ metric.label }}</span>
        <div class="metric-value">{{ metric.target }}</div>
        <p>{{ metric.description }}</p>
      </div>
    </div>

    <div class="panel">
      <h2 class="panel-title">验收链路</h2>
      <el-table :data="checks" size="large">
        <el-table-column prop="stage" label="阶段" width="170" />
        <el-table-column prop="evidence" label="证明材料" />
        <el-table-column prop="status" label="当前状态" width="160">
          <template #default="{ row }">
            <el-tag :type="row.status === '已接入' ? 'success' : 'warning'" effect="plain">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
const metrics = [
  { label: '幻觉率', target: '< 5%', description: '审核 Agent 检查事实与来源一致性。' },
  { label: '难度匹配', target: '>= 85%', description: '资源难度应匹配诊断画像分层。' },
  { label: '核心知识覆盖', target: '>= 90%', description: '生成内容覆盖检索到的核心知识点。' },
  { label: '评测样例', target: '50', description: '由离线脚本批量运行并生成结果。' },
]

const checks = [
  { stage: '诊断画像', evidence: '诊断题、答题记录、profile_id、weak_knowledge', status: '已接入' },
  { stage: '资源生成', evidence: 'generation_task、agent_trace、三类 learning_resource', status: '已接入' },
  { stage: '审核校验', evidence: 'review_report、primary_review、secondary_review、arbitration', status: '演示中' },
  { stage: '反馈更新', evidence: 'feedback、triggered_action、learning_path.needs_refresh', status: '已接入' },
  { stage: '离线评测', evidence: 'test_script 输出 hallucination/difficulty/coverage 指标', status: '待补强' },
]
</script>

<style scoped>
.metric-card p {
  margin: 8px 0 0;
  color: var(--app-muted);
  font-size: 13px;
  line-height: 1.5;
}
</style>
