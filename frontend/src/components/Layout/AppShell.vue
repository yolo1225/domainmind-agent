<template>
  <el-container class="app-shell">
    <el-aside class="app-aside" width="248px">
      <div class="brand">
        <strong>云川智汇</strong>
        <span>人工智能应用开发实训</span>
      </div>
      <el-menu :default-active="route.path" router>
        <el-menu-item index="/dashboard">演示工作台</el-menu-item>
        <el-menu-item index="/diagnostics">1. 诊断测评</el-menu-item>
        <el-menu-item index="/agents">2. Agent 协作</el-menu-item>
        <el-menu-item index="/resources">3. 学习资源</el-menu-item>
        <el-menu-item index="/reports">4. 学习报告</el-menu-item>
        <el-menu-item index="/metrics">5. 评测指标</el-menu-item>
        <el-menu-item index="/learners">学情画像</el-menu-item>
        <el-menu-item index="/knowledge">知识库管理</el-menu-item>
        <el-menu-item index="/domains">领域配置</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="app-header">
        <div>
          <strong>DomainMind Agent</strong>
          <span class="muted">MVP 演示环境</span>
        </div>
        <div class="header-right">
          <el-tag effect="plain">ai_app_dev</el-tag>
          <el-tag type="success">demo_admin</el-tag>
        </div>
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<style scoped>
.app-shell {
  min-height: 100vh;
  background: var(--app-shell);
}

.app-aside {
  border-right: 1px solid var(--app-border);
  background: #fff;
}

.brand {
  display: grid;
  gap: 5px;
  padding: 20px;
  border-bottom: 1px solid var(--app-border);
}

.brand strong {
  color: var(--app-text);
  font-size: 20px;
  letter-spacing: 0;
}

.brand span {
  color: var(--app-muted);
  font-size: 12px;
}

.app-aside :deep(.el-menu) {
  border-right: 0;
  padding: 10px;
}

.app-aside :deep(.el-menu-item) {
  height: 42px;
  border-radius: 8px;
  color: #344054;
}

.app-aside :deep(.el-menu-item.is-active) {
  background: var(--app-accent-soft);
  color: var(--app-accent);
  font-weight: 700;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--app-border);
  background: #fff;
}

.app-header > div:first-child {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.app-main {
  padding: 24px;
}

@media (max-width: 900px) {
  .app-shell {
    display: block;
  }

  .app-aside {
    width: 100% !important;
    border-right: 0;
    border-bottom: 1px solid var(--app-border);
  }

  .app-aside :deep(.el-menu) {
    display: flex;
    overflow-x: auto;
  }

  .app-aside :deep(.el-menu-item) {
    flex: 0 0 auto;
  }

  .app-main {
    padding: 16px;
  }
}
</style>
