# 云川智汇 - 多智能体个性化知识生成系统

本仓库是“领域知识个性化生成与多智能体协同决策系统”的 MVP 原型工程，主验证领域为 `ai_app_dev`（人工智能应用开发实训）。

## MVP 闭环

```text
learner profile -> diagnosis -> retrieval -> generation -> review -> decision -> feedback -> update
```

## 项目结构

```text
backend/      FastAPI + SQLAlchemy + LangGraph 分层骨架
frontend/     Vue 3 + TypeScript + Vite + Element Plus 页面骨架
data/         领域包、种子数据、评测样例、ChromaDB 本地目录
docs/         API、部署、环境和演示账号文档
test_script/  离线评测脚本入口
storage/      导出文件和运行期本地存储
```

## 快速启动

1. 复制环境变量：

```bash
cp .env.example .env
```

2. 使用 Docker Compose 构建并启动：

```bash
docker compose up -d --build
```

3. 初始化数据库表、种子数据和 ChromaDB 索引：

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.scripts.seed_data --json
docker compose exec backend python -m app.scripts.build_chroma_index --reset --json
```

4. 验证：

```bash
curl "http://localhost:8000/api/v1/health"
curl "http://localhost:8000/api/v1/knowledge/items?domain_code=ai_app_dev&limit=60"
curl "http://localhost:8000/api/v1/knowledge/search?query=RAG文档切片&n_results=3"
```

5. 访问：

- Frontend: http://localhost:5173
- Backend: http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health

如果只是重启已经初始化过的本地环境：

```bash
docker compose up -d
```

## 本地开发

后端：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## 当前初始化范围

- `/api/v1/health` 统一响应
- 演示账号、学习者、知识库、诊断、生成任务、资源、报告、领域配置、评测路由骨架
- Agent 标准消息、状态对象、节点职责与 LangGraph 入口占位
- SSE 任务事件推送接口
- Vue 应用壳、核心页面路由、Pinia 状态、Axios 客户端
- Agent 流程、雷达图、资源 Markdown 组件入口
