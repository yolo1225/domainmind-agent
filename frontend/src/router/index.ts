import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: () => import('@/pages/DashboardPage.vue') },
  { path: '/learners', component: () => import('@/pages/LearnerProfilePage.vue') },
  { path: '/diagnostics', component: () => import('@/pages/DiagnosticPage.vue') },
  { path: '/agents', component: () => import('@/pages/AgentWorkspacePage.vue') },
  { path: '/resources', component: () => import('@/pages/ResourcePage.vue') },
  { path: '/reports', component: () => import('@/pages/ReportPage.vue') },
  { path: '/knowledge', component: () => import('@/pages/KnowledgeAdminPage.vue') },
  { path: '/domains', component: () => import('@/pages/DomainConfigPage.vue') },
  { path: '/metrics', component: () => import('@/pages/MetricsPage.vue') },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
