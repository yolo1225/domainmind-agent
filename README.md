# 云川智汇 Cognivia - 多智能体个性化知识生成系统

主验证领域为 `ai_app_dev`（人工智能应用开发实训）。系统闭环为：

```text
诊断 -> 能力画像与学习路线 -> Candidate RAG 检索 -> 三类资源生成
-> 双模型审核 -> 自动局部修订 -> 原子发布 -> 反馈更新
```

当前实现还覆盖：首次三步建档、异步诊断评分、前置关系学习路径、资源内测验、错题巩固、
学习效果对比、导学评估、学习调整提案，以及文档驱动的领域知识导入、图谱预览与一次确认发布。
文档导入只构建知识与 Candidate 索引；正式题目由种子数据或领域管理中的 XLSX 题库导入提供。
活动 Agent 契约为 `agent-contract-v10`；运行时仅使用已发布领域的 active Candidate index 和
`active + certified` 正式题库。

正式题库按唯一用途分为 `diagnosis`、`graded_quiz`、`mastery_validation` 三个互斥题池。
错题巩固不是第四类题目：首次诊断和分阶测验的错题保存原题 ID，巩固时直接重做原题；通过只
关闭错题项，并作为画像更新信号，但不作为独立掌握证据。掌握状态由独立掌握检查题验证。题目直接从 MySQL 认证题库
筛选，只有知识正文或 Chunk 变化才需要重建 Candidate 向量索引。

## Docker 启动

```powershell
.\start.bat
```

`start.bat` 在空 Docker 卷中执行迁移、管理员初始化，并加载提交夹具 `ai_app_dev_submission_fixture_v1`：75 条知识点、106 条关系和 465 道活动题。若数据库已有普通开发种子或其他领域数据，启动会安全失败而不是混合基线；此时应清空 Docker 卷后再启动。

未配置真实模型或 Candidate index 时，服务、诊断和知识管理仍可用，但资源生成会返回 `CANDIDATE_RAG_NOT_READY`，不会回退到 mock 索引。开发环境如需使用较小的默认种子，可显式运行 `./scripts/demo.ps1 start`。

配置 `OPENAI_API_BASE`、`OPENAI_API_KEY`、三个审核/生成模型及 `EMBEDDING_MODEL` 后，显式构建真实索引：

```powershell
docker compose exec backend python -m app.scripts.build_chroma_candidate_index --domain-code ai_app_dev --reset --live --json
```

访问地址：

- Frontend: http://localhost:5173/
- Backend docs: http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health
- Dependencies: http://localhost:8000/api/v1/health/dependencies

## 验证

```powershell
docker compose exec backend python -m ruff check app tests
docker compose exec backend python -m compileall -q app tests
docker compose exec backend python -m pytest -q
docker compose exec backend python -m app.scripts.evaluate_rag --split development --live --json
```

`evaluate_rag` 只评测 active candidate index，真实评测会发送查询文本至配置的 embedding 服务。人工复核、mock embedding、旧 hash 检索和 V1/V2 运行链已移除。

## 文档入口

- [当前迭代计划](docs/current-iteration-plan.md)：当前交付顺序与已完成证据。
- [工程规范](docs/project-conventions.md)：开发、契约、测试与隐私约束。
- [API v1](docs/api-v1.md)：当前接口、认证与 SSE 说明。
- [部署说明](docs/deployment.md)：Docker 演示环境、健康检查与验证。
- [Agent Contract V10](docs/agent-contract-v10.md)：唯一活动 Agent 契约与审核发布边界。
- [系统设计](设计文档-人工智能应用开发实训多智能体个性化知识生成系统.md)：当前架构、RAG 输入输出与失败规则。
