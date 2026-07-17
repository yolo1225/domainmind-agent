<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">人工复核</h1>
        <p class="page-subtitle">处理双模型复审后仍未收敛的任务。决定会沿原 Thread 恢复，不会创建新任务。</p>
      </div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>

    <div class="panel filter-bar">
      <el-segmented v-model="status" :options="statusOptions" @change="load" />
    </div>

    <div class="panel">
      <el-table v-loading="loading" :data="items" empty-text="暂无待复核任务">
        <el-table-column prop="manual_review_id" label="复核编号" min-width="190" />
        <el-table-column prop="task_id" label="任务 / Thread" min-width="190" />
        <el-table-column prop="trigger_reason" label="触发原因" min-width="130" />
        <el-table-column label="状态" width="110">
          <template #default="scope">
            <el-tag :type="scope.row.status === 'pending' ? 'danger' : 'success'">
              {{ scope.row.status === 'pending' ? '待处理' : '已解决' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130">
          <template #default="scope">
            <el-button v-if="scope.row.status === 'pending'" type="primary" link @click="openDecision(scope.row)">复核</el-button>
            <span v-else>{{ decisionLabel(scope.row.decision) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" title="提交人工复核决定" width="520px">
      <el-form label-position="top">
        <el-form-item label="决定">
          <el-radio-group v-model="decision">
            <el-radio-button value="approve">批准发布</el-radio-button>
            <el-radio-button value="request_revision">要求修订</el-radio-button>
            <el-radio-button value="reject">驳回</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="复核说明">
          <el-input v-model="comment" type="textarea" :rows="4" maxlength="1000" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">确认并恢复任务</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { decideManualReview, listManualReviews, type ManualReviewItem } from '@/api/manualReviews'

const statusOptions = [{ label: '待处理', value: 'pending' }, { label: '全部', value: '' }]
const status = ref('pending')
const items = ref<ManualReviewItem[]>([])
const loading = ref(false)
const submitting = ref(false)
const dialogVisible = ref(false)
const selected = ref<ManualReviewItem | null>(null)
const decision = ref<'approve' | 'request_revision' | 'reject'>('approve')
const comment = ref('')

async function load() {
  loading.value = true
  try { items.value = await listManualReviews(status.value || undefined) }
  catch { ElMessage.error('人工复核列表加载失败') }
  finally { loading.value = false }
}
function openDecision(item: ManualReviewItem) {
  selected.value = item
  decision.value = 'approve'
  comment.value = ''
  dialogVisible.value = true
}
async function submit() {
  if (!selected.value) return
  submitting.value = true
  try {
    await decideManualReview(selected.value.manual_review_id, decision.value, comment.value)
    ElMessage.success('决定已提交，任务正在沿原 Thread 恢复')
    dialogVisible.value = false
    await load()
  } catch { ElMessage.error('复核决定提交失败') }
  finally { submitting.value = false }
}
function decisionLabel(value: string | null) {
  return ({ approve: '已批准', request_revision: '已要求修订', reject: '已驳回' } as Record<string, string>)[value || ''] || '未知状态'
}
onMounted(load)
</script>

<style scoped>
.filter-bar { display: flex; align-items: center; min-height: 56px; }
</style>
