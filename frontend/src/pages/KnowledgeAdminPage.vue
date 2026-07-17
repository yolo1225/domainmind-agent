<template>
  <section class="page knowledge-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">知识库管理</h1>
        <p class="page-subtitle">查看 MySQL 知识点，验证 ChromaDB 检索结果，为资源生成提供可追溯来源。</p>
      </div>
      <div class="toolbar">
        <el-button @click="showImport = !showImport">
          {{ showImport ? '收起导入' : '手动导入知识点' }}
        </el-button>
        <el-button :loading="rebuilding" @click="rebuildIndex">重建向量索引</el-button>
        <el-button :loading="loadingItems" @click="loadItems">刷新列表</el-button>
      </div>
    </div>

    <div v-if="showImport" class="panel import-panel">
      <div>
        <h2 class="panel-title">手动导入领域知识</h2>
        <p class="page-subtitle">
          适合教师临时补充一个知识点。保存后会标记为“待重建索引”，并提示后续执行向量索引重建。
        </p>
      </div>
      <el-form label-position="top" class="import-form" @submit.prevent>
        <div class="form-grid">
          <el-form-item label="知识点名称">
            <el-input v-model="importForm.name" placeholder="例如：RAG 文档切片策略" />
          </el-form-item>
          <el-form-item label="分类">
            <el-input v-model="importForm.category" placeholder="例如：RAG" />
          </el-form-item>
          <el-form-item label="难度">
            <el-input-number v-model="importForm.difficulty" :min="1" :max="5" />
          </el-form-item>
          <el-form-item label="标签">
            <el-input v-model="importForm.tagsText" placeholder="用逗号分隔，例如：rag, retrieval" />
          </el-form-item>
          <el-form-item label="来源标题">
            <el-input v-model="importForm.source_title" placeholder="例如：教师补充材料" />
          </el-form-item>
          <el-form-item label="来源 URL">
            <el-input v-model="importForm.source_url" placeholder="可选" />
          </el-form-item>
        </div>
        <el-form-item label="知识内容">
          <el-input
            v-model="importForm.content"
            type="textarea"
            :rows="7"
            placeholder="输入可用于生成与审核的知识内容，建议包含定义、适用场景、步骤、注意事项和示例。"
          />
        </el-form-item>
        <div class="submit-row">
          <span class="muted">导入后不会立即进入向量检索，需要重建索引。</span>
          <el-button type="primary" :loading="importing" @click="submitImport">保存知识点</el-button>
        </div>
      </el-form>
    </div>

    <el-alert
      v-if="lastImport"
      type="success"
      show-icon
      :closable="false"
      :title="`已导入 ${lastImport.item.name}，${lastImport.affected_learning_paths} 条学习路径已标记为需要刷新。`"
    />
    <el-alert
      v-if="lastRebuild"
      type="success"
      show-icon
      :closable="false"
      :title="`索引同步完成：处理 ${lastRebuild.indexed_items} 个知识点，更新 ${lastRebuild.indexed_chunks} 个分块，删除 ${lastRebuild.deleted_chunks} 个旧分块。`"
    />

    <div class="metric-grid">
      <div class="metric-card">
        <span class="metric-label">知识点</span>
        <div class="metric-value">{{ summary.total }}</div>
        <p>目标 {{ summary.target }}</p>
      </div>
      <div class="metric-card">
        <span class="metric-label">已索引</span>
        <div class="metric-value">{{ summary.indexed }}</div>
        <p>needs_reembedding = false</p>
      </div>
      <div class="metric-card">
        <span class="metric-label">分类数</span>
        <div class="metric-value">{{ summary.categories }}</div>
        <p>来自知识库字段</p>
      </div>
      <div class="metric-card">
        <span class="metric-label">当前领域</span>
        <div class="metric-value">ai</div>
        <p>人工智能应用开发实训</p>
      </div>
    </div>

    <div class="panel search-panel">
      <div class="search-row">
        <el-input
          v-model="query"
          clearable
          placeholder="输入检索词，例如：RAG 文档切片"
          @keyup.enter="runSearch"
        />
        <el-button type="primary" :loading="loadingSearch" @click="runSearch">检索知识库</el-button>
      </div>
      <el-empty v-if="!searchResult.length && !loadingSearch" description="输入关键词后查看 ChromaDB 召回结果" />
      <div v-else class="search-results">
        <article v-for="match in searchResult" :key="match.id" class="match-item">
          <div class="match-title">
            <strong>{{ match.name }}</strong>
            <el-tag size="small">{{ match.category }}</el-tag>
          </div>
          <p>{{ match.preview }}</p>
          <span class="muted">distance: {{ match.distance.toFixed(4) }}</span>
        </article>
      </div>
    </div>

    <div class="panel">
      <el-table v-loading="loadingItems" :data="items" height="520">
        <el-table-column prop="knowledge_id" label="知识点 ID" min-width="190" />
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column prop="category" label="分类" width="130" />
        <el-table-column prop="difficulty" label="难度" width="80" align="center" />
        <el-table-column label="标签" min-width="180">
          <template #default="{ row }">
            <div class="tag-list">
              <el-tag v-for="tag in row.tags" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="索引状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="row.needs_reembedding ? 'warning' : 'success'" size="small">
              {{ row.needs_reembedding ? '待重建' : '已同步' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="source_title" label="来源" min-width="220" />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="editVisible" title="编辑知识点" width="min(640px, 92vw)">
      <el-form v-if="editForm" label-position="top">
        <div class="form-grid">
          <el-form-item label="名称">
            <el-input v-model="editForm.name" />
          </el-form-item>
          <el-form-item label="分类">
            <el-input v-model="editForm.category" />
          </el-form-item>
          <el-form-item label="难度">
            <el-input-number v-model="editForm.difficulty" :min="1" :max="5" />
          </el-form-item>
        </div>
        <el-form-item label="知识内容">
          <el-input v-model="editForm.content" type="textarea" :rows="8" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editing" @click="submitEdit">保存修改</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  createKnowledgeItem,
  listKnowledgeItems,
  rebuildKnowledgeIndex,
  searchKnowledge,
  updateKnowledgeItem,
  type KnowledgeItem,
  type KnowledgeItemCreateResponse,
  type KnowledgeIndexResult,
  type KnowledgeSearchMatch,
} from '@/api/knowledge'

const items = ref<KnowledgeItem[]>([])
const searchResult = ref<KnowledgeSearchMatch[]>([])
const query = ref('RAG 文档切片怎么做')
const loadingItems = ref(false)
const loadingSearch = ref(false)
const importing = ref(false)
const rebuilding = ref(false)
const showImport = ref(false)
const lastImport = ref<KnowledgeItemCreateResponse | null>(null)
const lastRebuild = ref<KnowledgeIndexResult | null>(null)
const editVisible = ref(false)
const editing = ref(false)
const editForm = ref<KnowledgeItem | null>(null)
const mvpTarget = ref(50)
const importForm = ref({
  name: '',
  category: 'RAG',
  difficulty: 2,
  tagsText: '',
  content: '',
  source_title: '教师手动导入',
  source_url: '',
  license_note: 'manual-import',
})

const summary = computed(() => {
  const categories = new Set(items.value.map((item) => item.category)).size
  const indexed = items.value.filter((item) => !item.needs_reembedding).length
  return {
    total: items.value.length,
    target: mvpTarget.value,
    categories,
    indexed,
  }
})

async function loadItems() {
  loadingItems.value = true
  try {
    const data = await listKnowledgeItems('ai_app_dev', 100)
    items.value = data.items
    mvpTarget.value = data.mvp_target
  } catch (error) {
    ElMessage.error('知识点列表加载失败，请检查后端服务。')
  } finally {
    loadingItems.value = false
  }
}

async function runSearch() {
  const trimmedQuery = query.value.trim()
  if (!trimmedQuery) {
    ElMessage.warning('请输入检索词。')
    return
  }
  loadingSearch.value = true
  try {
    const data = await searchKnowledge(trimmedQuery, 'ai_app_dev', 5)
    searchResult.value = data.matches
  } catch (error) {
    ElMessage.error('知识库检索失败，请确认 ChromaDB 索引已构建。')
  } finally {
    loadingSearch.value = false
  }
}

async function submitImport() {
  const name = importForm.value.name.trim()
  const content = importForm.value.content.trim()
  if (!name || content.length < 10) {
    ElMessage.warning('请填写知识点名称，并输入至少 10 个字符的知识内容。')
    return
  }
  importing.value = true
  try {
    lastImport.value = await createKnowledgeItem({
      domain_code: 'ai_app_dev',
      name,
      category: importForm.value.category.trim() || '未分类',
      difficulty: importForm.value.difficulty,
      tags: importForm.value.tagsText
        .split(/[,，]/)
        .map((tag) => tag.trim())
        .filter(Boolean),
      content,
      source_title: importForm.value.source_title.trim() || '教师手动导入',
      source_url: importForm.value.source_url.trim() || null,
      license_note: importForm.value.license_note,
    })
    ElMessage.success('知识点已导入，请重建向量索引。')
    importForm.value.name = ''
    importForm.value.content = ''
    importForm.value.tagsText = ''
    await loadItems()
  } catch (error) {
    ElMessage.error('知识点导入失败，可能存在同名知识点或后端服务不可用。')
  } finally {
    importing.value = false
  }
}

async function rebuildIndex() {
  rebuilding.value = true
  try {
    lastRebuild.value = await rebuildKnowledgeIndex()
    ElMessage.success('向量索引同步完成。')
    await loadItems()
  } catch (error) {
    ElMessage.error('索引重建任务提交失败。')
  } finally {
    rebuilding.value = false
  }
}

function openEdit(item: KnowledgeItem) {
  editForm.value = { ...item, tags: [...item.tags] }
  editVisible.value = true
}

async function submitEdit() {
  if (!editForm.value || editForm.value.content.trim().length < 10) {
    ElMessage.warning('知识内容至少需要 10 个字符。')
    return
  }
  editing.value = true
  try {
    const item = editForm.value
    lastImport.value = await updateKnowledgeItem(item.knowledge_id, {
      name: item.name,
      category: item.category,
      difficulty: item.difficulty,
      tags: item.tags,
      content: item.content,
      source_title: item.source_title,
      source_url: item.source_url,
      license_note: item.license_note,
    })
    editVisible.value = false
    ElMessage.success('知识点已更新，请同步向量索引。')
    await loadItems()
  } catch (error) {
    ElMessage.error('知识点更新失败，请检查内容和关联关系。')
  } finally {
    editing.value = false
  }
}

onMounted(loadItems)
</script>

<style scoped>
.knowledge-page {
  gap: 18px;
}

.metric-card p {
  margin: 8px 0 0;
  color: var(--app-muted);
  font-size: 13px;
}

.search-panel {
  display: grid;
  gap: 14px;
}

.import-panel {
  display: grid;
  gap: 16px;
}

.import-form {
  display: grid;
  gap: 4px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0 12px;
}

.submit-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.search-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
}

.search-results {
  display: grid;
  gap: 10px;
}

.match-item {
  border: 1px solid var(--app-border);
  border-radius: 10px;
  padding: 12px;
}

.match-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.match-item p {
  margin: 8px 0;
  color: #344054;
  line-height: 1.6;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

@media (max-width: 760px) {
  .search-row,
  .form-grid {
    grid-template-columns: 1fr;
  }

  .submit-row {
    display: grid;
  }
}
</style>
