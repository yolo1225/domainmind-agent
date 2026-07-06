# AGENTS.md

## Project Role

This project is a competition prototype for a domain knowledge personalization and multi-agent collaborative decision system.

The main validation domain is `ai_app_dev`, Chinese name: 人工智能应用开发实训.

All development agents must treat this repository as an MVP-first project. The goal is not to build a full SaaS platform. The goal is to deliver a complete, demonstrable, measurable loop:

```text
learner profile -> diagnosis -> retrieval -> generation -> review -> decision -> feedback -> update
```

## Primary Documents

Before making architectural or feature decisions, read these documents:

1. `需求文档-领域知识个性化生成与多智能体协同决策系统.md`
2. `设计文档-人工智能应用开发实训多智能体个性化知识生成系统.md`
3. `docs/current-iteration-plan.md`
4. `docs/project-conventions.md`（Agent 执行规范）

If the documents conflict:

- Prefer the requirement document for product goals and scoring priorities.
- Prefer the design document for architecture and MVP implementation boundary.
- Prefer `docs/current-iteration-plan.md` for the current delivery order.
- Prefer `docs/project-conventions.md` for agent execution constraints and day-to-day engineering norms.

## Current Delivery Strategy

The project has already completed a first-pass frontend demonstration loop. The current iteration strategy is:

```text
frontend demo loop stability -> backend real capability fill-in -> reproducible evaluation -> demo packaging
```

Do not revert to a backend-only sequence that leaves the product flow invisible. New work should strengthen the visible competition demo while progressively replacing demo/rule-based backend logic with real implementations.

## MVP Scope

First-version delivery must prioritize:

- 1 domain package: `ai_app_dev`
- At least 50 real knowledge items
- At least 60 diagnostic questions
- At least 3 differentiated learner profiles
- Multi-agent loop with these agents:
  - Orchestrator Agent
  - Profile Analysis Agent
  - Knowledge Retrieval Agent
  - Content Generation Agent
  - Review and Validation Agent
  - Tutoring Agent, triggered by feedback
- 3 generated resource types:
  - `lecture`
  - `practice_guide`
  - `graded_quiz`
- Agent workflow visualization
- Learning profile/report visualization
- Knowledge management with manual import and index rebuild status
- Feedback-triggered correction, remedial explanation, or challenge task
- 50 evaluation cases and reproducible `test_script`

## Non-Goals For MVP

Do not spend first-version effort on these unless explicitly requested:

- Full JWT account lifecycle, registration, password recovery, or enterprise permission workflows
- `/api/v2` or complex long-term API compatibility governance
- `domain_versions`, `knowledge_item_versions`, `resource_versions` as mandatory tables
- Redis session cache
- Neo4j graph database
- WebSocket if SSE is enough
- Full online evaluation dashboard or human review workbench
- Decorative frontend landing pages

These may be mentioned as future extensions, but must not block the MVP loop.

## Technical Stack

Use the stack defined by the design document:

- Frontend: Vue 3, TypeScript, Vite, Element Plus, ECharts, Vue Flow, Pinia, Axios
- Backend: FastAPI, Python 3.12, SQLAlchemy, Alembic
- Agent orchestration: LangGraph `StateGraph`
- Relational database: MySQL 8
- Vector database: ChromaDB
- Model calls: OpenAI-compatible API
- Realtime progress: SSE
- Evaluation: `test_script`

Do not introduce new core frameworks without a clear need and explicit approval.

## Agent Design Rules

The system must not degrade into a single model call pretending to be multi-agent.

Each agent must have:

- Clear responsibility
- Independent system prompt
- Structured input and output
- Traceable run record
- Dedicated tool or validation logic where appropriate

Agent messages should use a standardized shape containing:

- sender
- receiver
- message type
- payload
- timestamp
- session or task ID

The main workflow is:

```text
START
 -> load_profile
 -> retrieve_knowledge
 -> generate_resource
 -> review_resource
 -> decide_next_step
    -> persist_resource when passed
    -> retrieve_knowledge when revision_required and revision_count < 2
    -> END when failed
 -> END
```

## Review And Anti-Hallucination Rules

The Review and Validation Agent is a scoring-critical component.

Generated resources must be reviewed on:

- factual accuracy
- source traceability
- difficulty match
- core knowledge coverage

Review must support dual-model cross-checking:

- `primary_review_model`
- `secondary_review_model`

Facts and source traceability must be checked by both model channels. If scores differ by more than 10 points, or one model passes and the other fails, trigger arbitration:

1. Retrieve sources again.
2. Review again.
3. If disagreement remains, mark `manual_review_required`.
4. Do not show unresolved resources to learners.

Every generated resource must include knowledge sources.

## Knowledge Update Rules

When knowledge items are added, changed, or imported:

1. Mark changed items as `needs_reembedding=true`.
2. Rebuild affected ChromaDB embeddings.
3. Use `knowledge_relations` to find prerequisite, dependent, and related knowledge points.
4. Mark affected learning paths as `needs_refresh=true`.
5. Regenerate the path when the learner or instructor opens the report.
6. If source or review rules changed, mark affected resources as `review_stale` when the field exists.

## Data Design Rules

Keep the database simple for MVP.

Mandatory first-version tables are the ones needed for:

- demo users and roles
- learners
- domains
- knowledge items and relations
- diagnostic questions and answer records
- learner profiles
- generation tasks
- agent runs and messages
- learning resources
- review reports
- feedback
- learning paths
- evaluation cases or script-imported metadata

Use JSON fields when they reduce unnecessary table sprawl and do not hide critical query needs.

## API Rules

Use `/api/v1`.

MVP auth should use demo accounts and roles. Formal JWT login may be added later, but it should not delay core delivery.

Every API response should include:

- `schema_version`
- `request_id`
- `data` or `error`

SSE should be used for generation progress and agent status events.

When adding or changing an endpoint, update the matching frontend API types under `frontend/src/api`.

## Frontend Rules

Build the actual tool interface first, not a marketing landing page.

Core pages:

- demo workspace
- learner profile and diagnosis
- Agent collaboration workspace
- learning resources
- learning report
- knowledge management
- domain configuration
- metric summary panel

Use Vue Flow for agent status visualization. Use ECharts for radar charts, heatmaps, graph views, and learning path visualization.

Keep the interface professional, compact, and demo-friendly.

All core pages must have:

- readable Chinese copy
- loading state
- empty state
- failure message
- route-level usefulness in the competition demo

## Evaluation Rules

The project must provide reproducible evaluation for:

- hallucination rate `< 5%`
- difficulty match accuracy `>= 85%`
- core knowledge coverage `>= 90%`
- learning path order accuracy, if implemented

The offline `test_script` is the source of truth for MVP evaluation. A frontend metric summary panel may display its output.

## Reliability And Privacy

LLM calls should retry at most 3 times with waits of 1s, 3s, and 5s.

Ordinary logs must not contain:

- real learner names
- full answer text
- complete learner profiles
- complete generated resources

Store summaries, IDs, scores, and status instead. Full debug payloads require an explicit debug switch.

## Local Development Rules

Docker Compose is the default demo runtime.

Preferred local URLs:

- Frontend: `http://localhost:5173/`
- Backend docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/api/v1/health`

Avoid running both Docker frontend and a separate local Vite server on port 5173. If both are needed, use different ports and clearly tell the user which URL is active.

## Development Style

Prefer simple, traceable implementations over clever abstractions.

When adding a feature:

1. Verify it supports the MVP loop or scoring criteria.
2. Follow the existing design document and the current iteration plan.
3. Keep APIs and data models stable enough for demo scripts.
4. Add focused tests for shared or scoring-critical logic.
5. Avoid unrelated refactors.

When unsure, choose the path that improves the competition demo and measurable evaluation first.
