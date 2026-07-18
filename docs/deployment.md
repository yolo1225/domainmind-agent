# 部署说明

## Docker Compose

```powershell
./scripts/demo.ps1 start
```

MySQL keeps port `3306` inside Docker. Host tools and IDE database connections use
`localhost:13306` by default; override it with `MYSQL_HOST_PORT` in `.env` when needed.

启动后访问：

- 前端：http://localhost:5173
- 后端文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/v1/health/dependencies

## 验收检查

1. `./scripts/demo.ps1 verify` 显示 MySQL、Chroma 和后端状态。
2. 知识点不少于 50，诊断题不少于 60。
3. `ready_for_live_demo=true` 且 `fixture_enabled=false`。
4. 前端工作台可打开，Agent 协同页面可接收同一任务 ID 的 SSE 事件。

重置会删除 MySQL、Chroma 和前端依赖卷，必须输入 `RESET` 二次确认：

```powershell
./scripts/demo.ps1 reset
```

完整操作和七分支验收见 `docs/demo-runbook.md`。
