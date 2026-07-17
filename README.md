# 云川智汇 - 多智能体个性化知识生成系统

本仓库是“领域知识个性化生成与多智能体协同决策系统”的 MVP 原型工程，主验证领域为 `ai_app_dev`（人工智能应用开发实训）。

## MVP 闭环

```text
learner profile -> diagnosis -> retrieval -> generation -> review -> decision -> feedback -> update
```

## 项目结构

```text
backend/      FastAPI + SQLAlchemy + LangGraph 统一八节点工作流
frontend/     Vue 3 + TypeScript + Vite + Element Plus 演示工作台
data/         领域包、50 个知识点、60 道诊断题和 50 个评测案例
docs/         API、部署、环境和演示账号文档
test_script/  baseline/live 评测与七分支验收入口
storage/      导出文件和运行期本地存储
```

## 快速启动

1. 复制环境变量并填写真实模型配置：

```bash
cp .env.example .env
```

正式验收必须设置三个模型名，并使用 `ALLOW_FIXTURE_LLM=false`。密钥只保存在未提交的 `.env`。

Windows 可以一键完成构建、迁移、种子初始化和索引重建：

```powershell
./scripts/demo.ps1 start
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
curl "http://localhost:8000/api/v1/health/dependencies"
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

## 真实评测与演示验收

真实评测必须按顺序执行，避免直接进行高成本的 50 案例调用：

```powershell
python test_script/run_live.py --stage smoke
python test_script/run_live.py --stage regression
python test_script/run_live.py --stage formal --xlsx
python test_script/demo_acceptance.py
```

`demo_acceptance.py` 会显式产生真实模型费用。异常分支可使用带模型名、任务 ID、时间和 `provider_mode=live` 的历史真实快照；未标识 fixture 不得作为验收证据。

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

## 已实现能力

- 唯一八节点 LangGraph、同一 task/thread ID 和可恢复人工复核
- 三类资源并行生成、两路真实模型审核、冲突复审和资源版本链
- 证据驱动反馈、导学会话、局部画像/路径/资源更新
- MySQL、独立 ChromaDB、增量索引重建和来源追溯
- SSE Agent 状态、协同图、资源导出、报告和指标页面
- 50 个 JSON 金标准案例、baseline/live 报告和任务/Agent P50/P95

当前仓库没有真实模型密钥，因此只完成了代码和自动化验证；真实 6/15/50 案例及七分支运行需在填写 `.env` 后执行。
