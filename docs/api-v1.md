# API v1 初始契约

所有响应遵循统一结构：

```json
{
  "schema_version": "1.0",
  "request_id": "...",
  "data": {},
  "error": null,
  "timestamp": "..."
}
```

## M0 已建立接口

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/auth/demo-accounts` | 演示账号 |
| GET | `/api/v1/learners` | 学习者样例 |
| GET | `/api/v1/learners/{learner_id}/profile` | 学情画像 |
| POST | `/api/v1/diagnostics/sessions` | 创建诊断测试 |
| POST | `/api/v1/diagnostics/sessions/{session_id}/submit` | 提交诊断测试 |
| GET | `/api/v1/knowledge/items` | 知识点列表 |
| POST | `/api/v1/knowledge/rebuild-index` | 重建向量索引任务 |
| POST | `/api/v1/generation-tasks` | 创建生成任务 |
| GET | `/api/v1/generation-tasks/{task_id}` | 获取生成任务 |
| GET | `/api/v1/generation-tasks/{task_id}/events` | SSE Agent 状态事件 |
| GET | `/api/v1/resources` | 学习资源列表 |
| POST | `/api/v1/resources/{resource_id}/feedback` | 提交资源反馈 |
| GET | `/api/v1/reports/learners/{learner_id}` | 学习报告 |
| GET | `/api/v1/domains` | 领域列表 |
| GET | `/api/v1/domains/{domain_code}/validate` | 领域配置检查 |
| GET | `/api/v1/evaluations/summary` | 评测指标汇总 |
