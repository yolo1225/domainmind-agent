# 部署说明

## Docker Compose

```bash
docker compose up --build
```

启动后访问：

- 前端：http://localhost:5173
- 后端文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/v1/health

## 验收检查

1. MySQL 容器健康。
2. 后端 `/api/v1/health` 返回 `status=ok`。
3. 前端工作台可打开。
4. Agent 协同页面可接收 SSE demo 事件。
