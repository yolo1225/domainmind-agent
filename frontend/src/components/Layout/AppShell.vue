<template>
  <el-container class="app-shell">
    <el-aside class="app-aside" width="248px">
      <div class="brand">
        <div class="brand-mark">云</div>
        <div>
          <strong>云川智汇</strong>
          <span>人工智能应用开发实训</span>
        </div>
      </div>
      <el-menu :default-active="route.path" router>
        <el-menu-item index="/dashboard"><el-icon><DataBoard /></el-icon><span>演示工作台</span></el-menu-item>
        <div class="menu-label">核心演示链路</div>
        <el-menu-item index="/diagnostics"><el-icon><Aim /></el-icon><span>诊断测评</span></el-menu-item>
        <el-menu-item index="/agents"><el-icon><Share /></el-icon><span>Agent 协同</span></el-menu-item>
        <el-menu-item index="/resources"><el-icon><Reading /></el-icon><span>学习资源</span></el-menu-item>
        <el-menu-item index="/reports"><el-icon><Document /></el-icon><span>学习报告</span></el-menu-item>
        <el-menu-item index="/metrics"><el-icon><TrendCharts /></el-icon><span>评测指标</span></el-menu-item>
        <div class="menu-label">管理与配置</div>
        <el-menu-item index="/manual-reviews"><el-icon><Stamp /></el-icon><span>人工复核</span></el-menu-item>
        <el-menu-item index="/learners"><el-icon><User /></el-icon><span>学情画像</span></el-menu-item>
        <el-menu-item index="/knowledge"><el-icon><Collection /></el-icon><span>知识库管理</span></el-menu-item>
        <el-menu-item index="/domains"><el-icon><Setting /></el-icon><span>领域配置</span></el-menu-item>
      </el-menu>
      <div class="aside-footer"><span class="status-dot is-done" /> 服务正常 <span class="footer-version">MVP v0.1</span></div>
    </el-aside>
    <el-container>
      <el-header class="app-header" height="auto">
        <div class="header-context">
          <div class="header-product"><strong>DomainMind Agent</strong><span class="muted">MVP 演示环境</span></div>
          <span class="header-divider" />
          <span class="header-location">{{ pageLabel }}</span>
        </div>
        <div class="header-right">
          <el-tag effect="plain" class="context-tag">ai_app_dev</el-tag>
          <el-tag effect="plain" class="context-tag">{{ learnerStore.selectedLearnerId }}</el-tag>
          <el-tag type="success" effect="light" class="context-tag"><span class="online-dot" /> demo_admin</el-tag>
        </div>
      </el-header>
      <el-main class="app-main"><router-view /></el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Aim, Collection, DataBoard, Document, Reading, Setting, Share, Stamp, TrendCharts, User } from '@element-plus/icons-vue'
import { useLearnerStore } from '@/stores/learnerStore'
const route = useRoute()
const learnerStore = useLearnerStore()

const pageLabel = computed(() => {
  const labels: Record<string, string> = {
    '/dashboard': '演示工作台',
    '/diagnostics': '诊断测评',
    '/agents': 'Agent 协同',
    '/resources': '学习资源',
    '/reports': '学习报告',
    '/metrics': '评测指标',
    '/manual-reviews': '人工复核',
    '/learners': '学情画像',
    '/knowledge': '知识库管理',
    '/domains': '领域配置',
  }
  return labels[route.path] ?? '工作区'
})
</script>

<style scoped>
.app-shell { min-height: 100vh; background: var(--app-shell); }
.app-aside { position: relative; display: flex; flex-direction: column; border-right: 1px solid var(--app-border); background: #fbfcfe; }
.brand { display: flex; align-items: center; gap: 11px; min-height: 82px; padding: 18px 20px; border-bottom: 1px solid var(--app-border); }
.brand-mark { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 9px; background: var(--app-accent); color: #fff; font-size: 18px; font-weight: 800; }
.brand strong { display: block; color: var(--app-text); font-size: 18px; letter-spacing: 0; }
.brand span { display: block; margin-top: 4px; color: var(--app-muted); font-size: 11px; }
.app-aside :deep(.el-menu) { flex: 1; border-right: 0; padding: 12px 10px 54px; background: transparent; }
.app-aside :deep(.el-menu-item) { height: 40px; margin: 2px 0; border-radius: 8px; color: #415066; font-size: 13px; }
.app-aside :deep(.el-menu-item .el-icon) { margin-right: 10px; color: #7c8ba1; font-size: 16px; }
.app-aside :deep(.el-menu-item.is-active) { background: var(--app-accent-soft); color: var(--app-accent); font-weight: 700; }
.app-aside :deep(.el-menu-item.is-active .el-icon) { color: var(--app-accent); }
.menu-label { padding: 18px 12px 6px; color: #8b99ab; font-size: 10px; font-weight: 700; letter-spacing: 0.08em; }
.aside-footer { position: absolute; right: 0; bottom: 0; left: 0; display: flex; align-items: center; gap: 7px; min-height: 44px; padding: 0 20px; border-top: 1px solid var(--app-border); background: #f7f9fc; color: var(--app-muted); font-size: 11px; }
.footer-version { margin-left: auto; color: #8795a8; }
.app-header { display: flex; min-height: 68px; align-items: center; justify-content: space-between; gap: 16px; border-bottom: 1px solid var(--app-border); background: rgb(255 255 255 / 0.96); padding: 12px 28px; }
.header-context, .header-product, .header-right { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.header-product strong { color: var(--app-text); font-size: 14px; }
.header-product .muted { font-size: 12px; }
.header-divider { width: 1px; height: 20px; background: var(--app-border); }
.header-location { color: var(--app-muted); font-size: 13px; font-weight: 600; }
.context-tag { min-height: 26px; }
.online-dot { display: inline-block; width: 6px; height: 6px; margin-right: 5px; border-radius: 50%; background: var(--app-success); vertical-align: 1px; }
.app-main { max-width: 1600px; width: 100%; margin: 0 auto; padding: 28px; }
@media (max-width: 900px) {
  .app-shell { display: block; }
  .app-aside { width: 100% !important; border-right: 0; border-bottom: 1px solid var(--app-border); }
  .brand { min-height: 66px; }
  .app-aside :deep(.el-menu) { display: flex; overflow-x: auto; padding: 8px 10px 12px; }
  .app-aside :deep(.el-menu-item) { flex: 0 0 auto; }
  .menu-label, .aside-footer { display: none; }
  .app-header { display: grid; align-items: start; padding: 12px 16px; }
  .header-right { justify-content: flex-start; }
  .app-main { padding: 18px 16px; }
}
</style>
