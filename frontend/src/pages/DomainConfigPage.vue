<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">领域配置</h1>
        <p class="page-subtitle">检查 ai_app_dev 领域包、知识点和诊断题是否满足 MVP 演示要求。</p>
      </div>
      <el-button :loading="loading" @click="load">检查配置</el-button>
    </div>

    <div class="panel">
      <el-descriptions v-if="domains[0]" border>
        <el-descriptions-item label="领域">{{ domains[0].name }}</el-descriptions-item>
        <el-descriptions-item label="编码">{{ domains[0].domain_code }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ domains[0].status }}</el-descriptions-item>
      </el-descriptions>
      <div v-else class="empty-hint">
        <strong>暂无领域数据</strong>
        <p>请先执行后端种子数据脚本。</p>
      </div>
    </div>

    <div v-if="validation" class="panel validation-panel">
      <div class="section-head">
        <h2 class="panel-title">配置校验</h2>
        <el-tag :type="validation.passed ? 'success' : 'warning'" effect="plain">
          {{ validation.passed ? '通过' : '需要处理' }}
        </el-tag>
      </div>
      <el-alert
        v-for="issue in validation.issues"
        :key="issue.message"
        :title="issue.message"
        type="warning"
        show-icon
      />
      <el-alert v-if="validation.passed" title="领域包满足当前 MVP 校验规则。" type="success" show-icon />
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { listDomains, validateDomain } from '@/api/domains'

const domains = ref<Array<{ domain_code: string; name: string; status: string }>>([])
const validation = ref<Awaited<ReturnType<typeof validateDomain>> | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    domains.value = await listDomains()
    validation.value = await validateDomain('ai_app_dev')
  } catch (error) {
    ElMessage.error('领域配置检查失败，请确认后端服务已启动。')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.validation-panel {
  display: grid;
  gap: 10px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
</style>
