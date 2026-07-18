# 三人团队 V2 Agent 算法实现推进计划

> 文档状态：执行版
>
> 适用范围：`ai_app_dev` MVP，多智能体算法实现阶段
>
> 当前基线：V2 Agent 合同已冻结，生产运行链仍为 V1；本阶段先完成 V2 算法实现和独立验证，暂不切换生产图。

## 1. 推进目标

本阶段的目标不是重写现有演示链，而是为六个 Agent 建立符合 V2 合同的可验证算法实现：

```text
V2 Input -> Agent 算法 -> V2 Output
```

最终应形成可被后续 V2 LangGraph、State、worker 和持久化层直接接入的实现，同时保持当前 V1 演示链可运行。

核心闭环为：

```text
画像分析 -> 知识检索 -> 内容生成 -> 双模型审核 -> 编排决策 -> 反馈导学 -> 画像更新
```

## 2. 共同约束

所有成员必须遵守以下边界：

1. 新 Agent 只导入 `app.agents.contracts` 和 `app.agents.state`。
2. 不修改冻结文件：
   - `backend/app/agents/contracts.py`
   - `backend/app/agents/state.py`
   - `backend/app/agents/contract_adapters.py`
   - `backend/app/agents/legacy_contracts.py`
   - `backend/app/agents/legacy_state.py`
   - `backend/tests/contracts/`
   - `docs/agent-contract-v2.md`
3. 当前 V1 运行链继续使用 `legacy_contracts` 和 `legacy_state`，不得进行仅替换 import 的 V1/V2 切换。
4. 本阶段不修改 `graphs.py`、`nodes.py`、`generation_worker.py` 和数据库表。
5. 每个 Agent 必须使用明确的 V2 Input/Output，不以 `dict[str, Any]` 作为正式边界。
6. 每个 Agent 必须有独立职责、独立 Prompt、结构化输出、异常处理和单元测试。
7. 普通日志只记录任务 ID、资源 ID、知识 ID、状态、摘要和分数，不记录完整画像、答案或资源正文。
8. 需要新增契约字段时，提交契约变更申请，不得自行修改公共模型。

## 3. 任务规划

### 3.1 画像与反馈

负责：

- Profile Analysis Agent
- Tutoring Agent
- 画像证据、画像版本和影响范围算法
- `ProfileSnapshot`、`EvidenceRef`、`AffectedScope` 相关测试

主要代码范围：

- `backend/app/agents/profile_agent.py`
- `backend/app/services/profile_service.py`
- `backend/app/agents/tutoring_agent.py`
- `backend/app/services/tutoring_service.py`

交付目标：

- 诊断结果能够生成五维能力画像；
- 能够识别薄弱知识、掌握类型和前置知识；
- 首轮困难反馈先追问，第二轮仍困难时给出解释；
- 单次主观反馈不直接修改画像；
- 计分题或多轮确认行为能够触发画像新版本；
- 输出画像变化维度、证据、置信度和受影响知识范围；
- 所有输出通过 V2 契约校验。

验收重点：

- `too_hard`、`too_easy`、`confusing`、`incorrect`、`helpful` 分支；
- 证据不足的 `no_change` 分支；
- 画像更新前后版本和证据关联；
- 能力分数范围 0-100，薄弱程度范围 1-5。

### 3.2 知识与生成

负责：

- Knowledge Retrieval Agent
- Content Generation Agent
- ChromaDB 检索和来源白名单；
- `RetrievedChunk`、`SourceRef` 和结构化资源内容。

主要代码范围：

- `backend/app/agents/retrieval_agent.py`
- `backend/app/agents/generation_agent.py`
- `backend/app/rag/`

交付目标：

- 支持 `remedial`、`consolidation`、`challenge` 三种检索策略；
- 根据画像和学习目标确定目标难度；
- 补充 prerequisite、dependent、related 知识；
- 最多返回 12 条带来源的结构化检索片段；
- 生成 `lecture`、`practice_guide`、`graded_quiz` 三类结构化资源；
- 资源来源必须属于检索结果的白名单；
- Markdown 由结构化内容确定性渲染；
- 审核修订时支持根据新查询重新检索。

验收重点：

- 检索结果的 `covered_knowledge_ids` 和 `missing_knowledge_ids` 不重叠；
- 每个片段都有稳定 `source_ref_id`；
- 分级测验至少包含 foundation、improvement、challenge 三个等级；
- 资源正文实际使用的来源与 `source_refs` 完全一致；
- 模型失败、JSON 失真和来源越权能够被拒绝。

### 3.3 审核与编排

负责：

- Review Validation Agent
- Orchestrator Agent
- V2 合同使用协调；
- 共享 fixture、质量测试和跨 Agent 验证。

主要代码范围：

- `backend/app/agents/review_agent.py`
- `backend/app/agents/orchestrator.py`
- `backend/tests/unit/` 中的 V2 Agent 测试

交付目标：

- 两个审核模型独立检查事实、来源、难度和核心覆盖；
- 分数差异超过 10 分或通过状态不一致时触发仲裁；
- 仲裁重新检索来源并重新审核；
- 持续分歧输出 `manual_review_required`；
- 自动修订最多两次；
- 支持通过、修订、失败、拒绝和人工复核决策；
- 收集契约变更申请，但不直接修改冻结合同。

验收重点：

- 双模型调用结果独立保存；
- `ArbitrationResult` 包含查询词、补充来源和两路复审结果；
- 未解决分歧不能判定为通过；
- 修订计划包含资源类型、问题代码、检索词和必需修改项；
- 编排 Agent 不生成或改写教学内容。

## 4. 实施阶段

### 阶段一：共同基线

1. 阅读 `docs/agent-contract-v2.md`、V2 Schema 和示例。
2. 为每个 Agent 确认唯一 Input、Output 和 State 所有权。
3. 准备最小合法输入 fixture。
4. 确认代码修改范围，避免同时修改共享文件。
5. 运行现有合同测试，保存基线结果。

完成标准：

- 所有最小 fixture 可以通过 Pydantic 校验；
- 当前 V1 测试基线通过。

### 阶段二：算法实现

实现Agent 算法。每个工作包必须先实现可测试的纯算法，再接入 V2 Agent 边界。

每日提交要求：

- 只提交通过测试的增量；
- 不修改冻结契约；
- 不修改顶层图和 worker；
- 在提交说明中记录输入、输出、测试和已知限制。

### 阶段三：跨 Agent 交叉验证

共同验证以下数据流：

```text
ProfileSnapshot
    -> RetrievalPlan
    -> RetrievedChunk + SourceRef
    -> GeneratedResourceArtifact
    -> ReviewReport + ArbitrationResult
    -> FinalizeTaskOutput
```

反馈流必须验证：

```text
FeedbackContext
    -> InterpretFeedbackOutput
    -> AnalyzeProfileOutput
    -> no_change 或新的 ProfileSnapshot
```

交叉验证至少覆盖：

- 画像输出能够被检索输入消费；
- 检索来源能够被生成资源严格引用；
- 生成资源能够被审核输入接受；
- 审核修订计划能够生成新的检索查询；
- 反馈结果能够被画像 Agent 正确判断；
- `task_id`、`contract_version` 和来源 ID 在链路中保持一致。

### 阶段四：V2 集成切换

算法和交叉测试完成后，再处理：

- V2 LangGraph 节点输入构造；
- V2 State patch 和 State 所有权；
- worker 和 checkpoint；
- `agent_runs`、`agent_messages` 持久化；
- SSE 事件和任务状态；
- V1/V2 端到端回归；
- V1 legacy 链下线条件。

该阶段不与 Agent 算法实现并行，避免算法、State 和 worker 同时变化导致问题无法定位。

## 5. 测试要求

每位成员必须提交：

- 正常路径单元测试；
- 空输入、边界值和重复数据测试；
- 模型失败、检索失败或来源缺失测试；
- V2 Output 契约校验测试；
- 至少一个负责链路内的跨 Agent 测试。

团队整体必须验证：

- 三类资源都能生成并通过结构校验；
- 资源来源可追溯且没有越权引用；
- 两路审核结果独立保存；
- 审核分歧确实重新检索并复审；
- 单次反馈不会修改画像；
- 有效证据可以创建画像新版本；
- 自动修订次数不超过 2；
- 人工复核支持批准、要求修订和驳回；
- 当前 V1 演示链不回归。

统一检查命令：

```powershell
cd backend
python -m compileall app tests
pytest tests/contracts tests/unit
```

## 6. V1 到 V2 的迁移风险

算法核心可以复用，但以下边界必须预留适配工作：

| 部分 | 后续改动 | 原因 |
|---|---|---|
| 画像、反馈和路由规则 | 小到中 | 主要是输出字段映射和枚举转换 |
| 检索结果 | 中 | V2 要求 `RetrievedChunk`、`SourceRef` 和用途字段 |
| 内容生成 | 中到大 | V2 使用结构化资源联合类型和确定性 Markdown 渲染 |
| 审核结果 | 中到大 | V2 使用嵌套评分、FactCheck、ReviewIssue 和 ArbitrationResult |
| AgentMessage | 中 | V2 限制 payload 结构和消息类型 |
| Graph State、worker 和 checkpoint | 大 | V1 平铺 State 需要迁移到 V2 节点独占 State |

禁止通过“只替换 import”完成迁移。正确迁移路径是：

```text
V2 算法核心
    -> V2 Agent 边界
    -> V2 节点适配
    -> V2 State / worker / checkpoint
    -> 端到端切换
```

## 7. 本阶段不做的工作

- 不修改 V1/V2 合同和 Schema；
- 不立即切换生产 LangGraph；
- 不修改数据库表结构；
- 不引入 Redis、Neo4j 或新的核心框架；
- 不把六个 Agent 简化成单次模型调用；
- 不进行前端页面重构；
- 不把临时材料上传和正式知识库入库纳入本阶段。

## 8. 责任确认

- 冻结合同只能由指定合同维护者统一变更；
- 任何 Agent 实现不得为了通过测试而修改公共契约。
