<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">学情画像</h1>
        <p class="page-subtitle">查看演示学习者的画像分层、目标领域和能力等级。</p>
      </div>
      <el-button :loading="loading" @click="load">刷新样例</el-button>
    </div>
    <div class="panel">
      <el-table v-loading="loading" :data="learners">
        <el-table-column prop="learner_id" label="学习者" />
        <el-table-column prop="profile_type" label="画像类型" />
        <el-table-column prop="target_domain" label="领域" />
        <el-table-column prop="ability_level" label="能力等级" />
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { listLearners, type LearnerSummary } from '@/api/learners'

const learners = ref<LearnerSummary[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    learners.value = await listLearners()
  } catch (error) {
    ElMessage.error('学习者样例加载失败，请确认后端服务已启动。')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
