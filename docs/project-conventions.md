# Agent 执行规范

> 更新日期：2026-07-06  
> 目标读者：开发代理、代码生成代理、协作智能体。  
> 用途：约束后续实现行为，避免偏离当前 MVP 交付路线。

## 1. 总原则

项目定位是比赛 MVP 原型，不是完整 SaaS 平台。

开发优先级固定为：

```text
可演示闭环 > 可复现指标 > 架构完整性 > 企业级扩展
```

开发代理新增功能前必须先自检三个问题：

1. 是否支撑 `learner profile -> diagnosis -> retrieval -> generation -> review -> decision -> feedback -> update`？
2. 是否能提升比赛评分中的完整性、创新性、用户体验或指标证明？
3. 是否能在演示路线中被看见、被解释、被复现？

如果答案不明确，放入后续扩展，不进入当前 MVP。

## 2. 前端规范

技术栈固定：

- Vue 3
- TypeScript
- Vite
- Element Plus
- ECharts
- Vue Flow
- Pinia
- Axios

页面建设规则：

- 优先建设真实工具界面，不做营销落地页。
- 首页是演示工作台，必须引导完整流程。
- 核心页面固定包括：诊断测评、Agent 协作、学习资源、学习报告、知识库管理、领域配置、评测指标。
- 前端可以先用 demo 数据跑顺体验，但 API 类型、字段和状态必须按真实后端契约设计。
- 页面中文必须可读，禁止提交乱码。
- 所有核心操作必须有加载、成功、失败、空状态。
- 不新增大型 UI 框架，不引入与 Element Plus 冲突的组件系统。

交互约定：

- 知识库新增或修改后，前端必须提示“需要重建向量索引”。
- 生成资源必须展示资源类型、难度、审核状态和知识来源。
- 资源反馈必须展示触发的动作，例如补救解释、挑战任务、资源修订。
- Agent 页面必须展示每个节点的职责和运行状态，不能只显示一个“生成中”。
- 指标页展示评测目标时，必须说明离线 `test_script` 是最终来源。

## 3. 后端规范

技术栈固定：

- FastAPI
- Python 3.12
- SQLAlchemy
- Alembic
- MySQL 8
- ChromaDB
- LangGraph `StateGraph`
- OpenAI-compatible API
- SSE

API 规则：

- 基础路径固定 `/api/v1`。
- 所有响应必须使用统一结构：`schema_version`、`request_id`、`data` 或 `error`。
- MVP 认证使用演示账号和角色，不阻塞核心闭环。
- 新增接口必须优先服务演示路线。
- 修改 API 字段时要同步更新 `frontend/src/api` 类型。

服务实现规则：

- 允许保留 demo/rule-based 实现作为过渡，但必须在代码或文档中标明边界。
- 生成任务应逐步从 `demo_flow_service` 迁移到正式 service 和 Agent 节点。
- 每个 Agent 必须有独立职责、结构化输入输出、运行记录和消息记录。
- SSE 事件应来自真实任务状态或 `agent_runs`，不长期依赖硬编码步骤。

## 4. 知识库规范

知识点至少包含：

- `name`
- `category`
- `difficulty`
- `tags`
- `content`
- `source_title`
- `source_url`（可选）
- `license_note`
- `needs_reembedding`

知识更新规则：

1. 新增、修改或导入知识点后，必须设置 `needs_reembedding=true`。
2. 使用 `knowledge_relations` 找出前置、后继、相关知识点。
3. 影响到的学习路径必须设置 `needs_refresh=true`。
4. 向量索引重建完成后，才可清除 `needs_reembedding`。
5. 如果来源或审核规则变化，相关资源应标记为 `review_stale`（字段可后续补充）。

当前 MVP 允许先支持单条手动导入；批量 Excel/JSON 导入作为下一阶段能力。开发代理不得因为批量导入未完成而阻塞演示闭环。

## 5. Agent 规范

系统不能退化为单次模型调用。

核心 Agent：

- Orchestrator Agent
- Profile Analysis Agent
- Knowledge Retrieval Agent
- Content Generation Agent
- Review and Validation Agent
- Tutoring Agent

每个 Agent 必须满足：

- 有独立系统提示词。
- 有结构化输入输出。
- 写入 `agent_runs`。
- 关键消息写入 `agent_messages`。
- 输出中不能包含完整敏感学习者画像或完整资源内容，普通日志只存摘要、ID、状态和分数。

主流程：

```text
START -> prepare_task
prepare_task -> analyze_profile       when trigger_type = initial_generation
prepare_task -> interpret_feedback    when trigger_type = resource_feedback
interpret_feedback -> analyze_profile
analyze_profile -> finalize_task      when no generation, review or regeneration is required
analyze_profile -> retrieve_knowledge when generation, review or regeneration is required
retrieve_knowledge -> generate_resource -> review_resource -> finalize_task
finalize_task -> END                  when completed, no_change, failed or rejected
finalize_task -> retrieve_knowledge   when revision_required and revision_count < 2
finalize_task -> human_review         when manual_review_required or assisted approval is pending
human_review -> retrieve_knowledge    when request_revision
human_review -> finalize_task         when approve or reject
```

约束：

- `build_learning_graph()` 是唯一顶层图构建函数，worker 不得复制一套图定义。
- 首次生成和反馈调优都使用 `generation_tasks.public_id` 作为 `task_id/thread_id`。
- 自然语言反馈进入导学会话；快捷标签、评分和选中文本只作为辅助证据。
- 单次 `too_hard/too_easy` 不得直接修改画像；证据不足时保存 `no_change` 和理由。
- 临时材料上传属于紧随 P0 的 P1；未来实现时必须任务级隔离，不得自动入库或直接更新画像。

### 5.1 Agent 契约修改规范

`docs/agent-contract-v2.md`、`backend/app/agents/contracts.py`、`backend/app/agents/state.py` 和对应 Schema 是已冻结契约。契约由一名指定负责人统一维护，其他成员及开发代理在实现具体 Agent 时必须将以下文件视为只读：

- `backend/app/agents/contracts.py`
- `backend/app/agents/state.py`
- `backend/app/agents/contract_adapters.py`
- `backend/app/agents/legacy_contracts.py`
- `backend/app/agents/legacy_state.py`
- `backend/tests/contracts/`
- `docs/agent-contract-v2.md`
- `docs/contracts/v2/`

具体 Agent 实现者不得为了让代码、Prompt 或测试通过，擅自修改字段名、类型、枚举、必填性、默认值、State 字段所有权、Schema 或顶层图。实现与契约不一致时，先在 Agent 内按已有契约适配；确实无法表达时，停止修改共享文件并提交契约变更申请。

变更申请必须说明申请字段或规则、所属输入/输出、生产与消费节点、使用原因、是否可空、默认值和兼容性影响。只有契约负责人可以决定是否修改，并统一更新模型、State、适配器、示例、Schema、测试和文档。破坏性变更必须升级契约版本。

当前 V1 运行链只允许导入 `legacy_contracts` 和 `legacy_state`；新 Agent 只允许导入正式 `contracts` 和 `state`。禁止只替换 import 而保留 V1 数据结构。

## 6. 审核与反幻觉规范

Review and Validation Agent 是评分关键组件。

生成资源必须检查：

- factual accuracy
- source traceability
- difficulty match
- core knowledge coverage

双模型审核规则：

- `primary_review_model` 和 `secondary_review_model` 都要检查事实和来源。
- 分差超过 10 分，或一方通过一方失败，必须触发仲裁。
- 仲裁流程：重新检索来源 -> 重新审核 -> 仍不一致则 `manual_review_required`。
- 未通过或人工复核资源不得默认展示给学习者。

## 7. 评测规范

离线 `test_script` 是 MVP 指标的事实来源。开发代理不得用前端展示值替代离线评测结果。

必须可复现：

- hallucination rate `< 5%`
- difficulty match accuracy `>= 85%`
- core knowledge coverage `>= 90%`
- learning path order accuracy（如实现）

前端指标页只能展示或解释结果，不能替代离线评测。

## 8. 本地运行规范

Docker Compose 是默认演示环境。

推荐访问：

- Frontend: `http://localhost:5173/`
- Backend Docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/api/v1/health`

如果同时存在 Docker 前端和本地 Node/Vite，优先保留 Docker 前端，避免 `localhost` 与 `127.0.0.1` 指向不同服务。

前端改动后至少执行：

```bash
cd frontend
npm run build
```

后端改动后至少执行：

```bash
cd backend
python -m compileall app tests
```

如果本地环境安装了测试依赖，应执行对应单元测试和接口测试。

## 9. 文档规范

文档分工：

- 根目录需求文档：产品目标、评分优先级。
- 根目录设计文档：技术边界、架构设计。
- `docs/current-iteration-plan.md`：当前实际迭代计划。
- `docs/project-conventions.md`：当前工程规范。
- `AGENTS.md`：开发代理必须遵守的简版规则入口。

当实现路线与原设计文档发生偏移时，开发代理先更新 `docs/current-iteration-plan.md`，再决定是否回写根目录设计文档。
