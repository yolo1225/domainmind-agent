# Agent Contract V2

> 状态：已冻结
> 版本：`agent-contract-v2`
> 适用范围：后续实现的六个 Agent 与八个 LangGraph 节点
> 运行时：当前 V1 图暂不切换，禁止 V1/V2 混用

## 1. 责任边界

契约负责人独占修改 `contracts.py`、`state.py`、`contract_adapters.py`、两个 `legacy_*` 过渡文件、本文档、Schema 和契约测试。其他开发者只实现具体 Agent，不得修改公共字段、State 或顶层图。

契约变更申请必须包含：

```text
申请字段：
所属输入或输出：
生产该字段的节点：
消费该字段的节点：
使用原因：
是否可以为空：
默认值：
对现有契约的影响：
```

破坏性变更不允许继续使用 V2，必须升级为 `agent-contract-v3`。

### 1.1 V1/V2 物理隔离

```text
contracts.py          # 正式 V2 契约，新 Agent 唯一入口
state.py              # 正式 V2 AgentGraphState
legacy_contracts.py   # 当前 V1 Agent 临时使用
legacy_state.py       # 当前 V1 图、服务和 worker 临时使用
```

新代码禁止导入 `legacy_contracts` 或 `legacy_state`。现有 V1 运行链禁止从正式 `contracts` 或 `state` 获取兼容类型。正式文件不重新导出 legacy 类型。

当六个 Agent、节点适配、worker 和持久化全部切换到 V2 后，一次性删除两个 legacy 文件并将运行时契约常量升级为 `agent-contract-v2`。不允许仅替换 import 而保留 V1 数据结构。

## 2. 通用规则

1. V2 Pydantic 模型统一使用 `ConfigDict(extra="forbid")`。
2. 节点输入输出必须携带 `contract_version` 和 `task_id`。
3. 任务与会话使用 `generation_tasks.public_id`，同时作为 LangGraph `thread_id`。
4. Agent 只接收对应 Input，只返回对应 Output，不接收或返回任意 `dict[str, Any]`。
5. 节点输出通过 `*_output_to_patch()` 写入它拥有的唯一 State 字段。
6. State 不存放数据库会话、模型客户端、Chroma 客户端或其他不可序列化对象。
7. 普通日志和 AgentMessage 只保存摘要、ID、分数、状态和指标，不保存完整画像、答案或资源正文。

## 3. 公共枚举

| 枚举 | 取值 |
|------|------|
| `AgentName` | `orchestrator_agent`, `profile_analysis_agent`, `knowledge_retrieval_agent`, `content_generation_agent`, `review_validation_agent`, `tutoring_agent` |
| `ResourceType` | `lecture`, `practice_guide`, `graded_quiz` |
| `TriggerType` | `initial_generation`, `resource_feedback` |
| `ExecutionMode` | `auto`, `assisted` |
| `ProfileType` | `beginner`, `intermediate`, `advanced`, `practice_oriented` |
| `GenerationStrategy` | `remedial`, `consolidation`, `challenge` |
| `FeedbackIntent` | `too_hard`, `too_easy`, `confusing`, `incorrect`, `helpful`, `other` |
| `RecommendedAction` | `ask_follow_up`, `explain`, `challenge`, `review`, `regenerate`, `no_change` |
| `TaskDecision` | `pending`, `completed`, `no_change`, `revision_required`, `manual_review_required`, `failed`, `rejected` |
| `ReviewDecision` | `passed`, `revision_required`, `manual_review_required`, `rejected` |
| `MessageType` | `command`, `observation`, `result`, `review`, `decision`, `feedback`, `error` |

## 4. 六个 Agent 映射

| Agent | 输入 | 输出 |
|-------|------|------|
| Orchestrator Agent | `PrepareTaskInput`, `FinalizeTaskInput`, `HumanReviewInput` | 各自对应 Output |
| Profile Analysis Agent | `AnalyzeProfileInput` | `AnalyzeProfileOutput` |
| Knowledge Retrieval Agent | `RetrieveKnowledgeInput` | `RetrieveKnowledgeOutput` |
| Content Generation Agent | `GenerateResourceInput` | `GenerateResourceOutput` |
| Review Validation Agent | `ReviewResourceInput` | `ReviewResourceOutput` |
| Tutoring Agent | `InterpretFeedbackInput` | `InterpretFeedbackOutput` |

Agent 实现必须使用以上模型作为 `execute()` 边界，Prompt、RAG、工具和模型调用只允许存在于契约边界内部。

## 5. 八节点契约与 State 所有权

| 节点 | 输入 | 输出 | State 字段 |
|------|------|------|------------|
| `prepare_task` | `PrepareTaskInput` | `PrepareTaskOutput` | `prepare_task` |
| `interpret_feedback` | `InterpretFeedbackInput` | `InterpretFeedbackOutput` | `interpret_feedback` |
| `analyze_profile` | `AnalyzeProfileInput` | `AnalyzeProfileOutput` | `analyze_profile` |
| `retrieve_knowledge` | `RetrieveKnowledgeInput` | `RetrieveKnowledgeOutput` | `retrieve_knowledge` |
| `generate_resource` | `GenerateResourceInput` | `GenerateResourceOutput` | `generate_resource` |
| `review_resource` | `ReviewResourceInput` | `ReviewResourceOutput` | `review_resource` |
| `finalize_task` | `FinalizeTaskInput` | `FinalizeTaskOutput` | `finalize_task` |
| `human_review` | `HumanReviewInput` | `HumanReviewOutput` | `human_review` |

worker 可在执行前提供 `task_request`、`current_profile`、`diagnostic_summary`、`feedback_context` 和 `revision_plan`。它们是外部输入，不属于任何 Agent 的输出。

## 6. 关键对象

### 6.1 画像与证据

`ProfileSnapshot` 固定包含画像 ID、版本、类型、五维能力、薄弱知识和盲区 ID。能力分数范围为 0-100，薄弱程度范围为 1-5。

`EvidenceRef` 固定包含证据 ID、类型、脱敏摘要、置信度、确认状态和可选知识 ID。快捷标签和一次主观反馈不能由 Tutoring Agent 直接输出画像更新结论。

### 6.2 检索

`RetrieveKnowledgeOutput.chunks` 最多 12 条。每条 `RetrievedChunk` 必须有 chunk ID、knowledge ID、难度、正文、相似度、匹配方式、用途和 `SourceRef`。

`SourceRef` 必须包含稳定来源 ID、knowledge ID、来源标题和授权说明。

### 6.3 生成

模型输出的事实来源必须是 `GenerationRequirements.source_whitelist` 的子集。结构化正文中实际使用的来源 ID 必须与 `GeneratedResourceArtifact.source_refs` 完全一致，不允许隐藏引用或携带未使用来源。三类资源使用可辨别联合类型：

- `LectureContent`：适配对象、目标、前置知识、核心概念、误区和小结。
- `PracticeGuideContent`：环境、目标、步骤、命令/代码、预期结果、排错和验收标准。
- `GradedQuizContent`：至少 6 题，必须同时包含 `foundation`、`improvement`、`challenge` 三个级别。

`GeneratedResourceArtifact.content_md` 必须等于 `render_resource_markdown()` 对结构化内容的确定性渲染结果，不允许模型同时自由维护 JSON 和 Markdown。

### 6.4 审核与决策

`ModelReview` 固定审核事实、来源、难度和覆盖四项 0-100 分数。`FactCheck` 对每条可核验声明保存支持状态和来源 ID。

`ArbitrationResult` 记录是否重新检索、补证查询、新来源、两路复审和分歧是否依然存在。触发仲裁时必须包含补证查询和两路复审；未解决分歧必须输出 `manual_review_required`。`passed`、`manual_review_required`、审核决策和最终任务决策必须保持一致，矛盾组合会在契约校验阶段被拒绝。

## 7. AgentMessage

V2 AgentMessage 必须包含：

```text
contract_version
message_id
sender
receiver
message_type
payload.node_name
payload.summary
timestamp
session_id
task_id
```

`payload` 只允许引用 ID、决策、错误码和结构化指标。SSE 运行状态不作为 AgentMessage 类型。

## 8. Schema 与示例

Schema 和示例位于 `docs/contracts/v2/`：

- `agent-contract-v2.schema.json`
- `agent-message.example.json`
- `initial-generation.example.json`
- `feedback-no-change.example.json`
- `human-review.example.json`
- `resource-types.example.json`

生成命令：

```powershell
cd backend
python -m app.scripts.export_agent_contract_v2
```

契约测试会重新计算并比较这些工件，手工修改生成文件会导致测试失败。
