# 部署说明

> 最近同步：2026-08-29。默认演示环境为 Docker Compose；服务启动后不会自动构建真实
> Candidate 索引，避免未授权的 embedding 调用。

## Docker Compose

```powershell
.\start.bat
```

`start.bat` 使用空库加载提交夹具 `ai_app_dev_submission_fixture_v1`（75 条知识点、106 条关系、465 道活动题）。它不会覆盖普通开发种子或其他领域数据；需切换基线时，先执行 `docker compose down -v`。`./scripts/demo.ps1 start` 保留为开发用的轻量种子启动入口。

MySQL keeps port `3306` inside Docker. Host tools and IDE database connections use
`localhost:13306` by default; override it with `MYSQL_HOST_PORT` in `.env` when needed.

启动后访问：

- 前端：http://localhost:5173
- 后端文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/v1/health/dependencies

首次演示前，配置 `.env` 中的 OpenAI-compatible 生成、双审核与 embedding 模型后，显式构建
主领域索引：

```powershell
docker compose exec backend python -m app.scripts.build_chroma_candidate_index --domain-code ai_app_dev --reset --live --json
```

当 `rag.ready=false` 或索引版本/模型版本不一致时，诊断和知识管理仍可用，但资源生成会返回
`CANDIDATE_RAG_NOT_READY`，不会回退到 mock 索引。

## 验收检查

1. `./scripts/demo.ps1 verify` 显示 MySQL、Chroma 和后端状态。
2. 知识点不少于 50，诊断题不少于 60。
3. `ready_for_live_demo=true`、`evaluation_overrides_enabled=false`，且活动 Candidate RAG 就绪。
4. 前端工作台可完成首次建档；资源、报告、错题巩固和领域管理页面均可打开。
5. 领域管理按“知识导入”完成 Candidate 发布后，进入“题库”下载 XLSX 缺口模板并导入正式题目。
   每行须通过模板、知识点、用途、结构、答案和解析的确定性校验；整份模板确认发布后领域才可从 `preparing` 进入 `ready`。题目来源在资源生成时按关联知识点动态检索。
   已就绪领域的增量资料会先形成变更集：知识、关系和候选索引保持暂存，题目可分批导入；全部
   缺口通过后点击“一次启用变更”，才会切换学习者可见的知识、索引和题库。
   来源文档的删除操作实际为“撤回来源”：历史题目、答题记录和导入证据会保留，失去全部来源的
   知识点被标为 retired，随后重建索引。
6. 生成任务 SSE、诊断 SSE 与导学 SSE 使用真实任务/运行记录；Agent 运行摘要通过受控任务 API
   留痕，学习者页面不展示原始 Agent payload。
7. 活动任务使用 `agent-contract-v10`；审核补检索为空不会单独导致任务失败，最终发布按整包三项
   官方指标判定。

题库导入规则升级后，未发布的旧批次会取消，需重新下载 v3 模板并上传：

```powershell
docker compose exec backend python -m app.scripts.recertify_question_bank_v2 --domain-code ai_app_dev --dry-run
docker compose exec backend python -m app.scripts.recertify_question_bank_v2 --domain-code ai_app_dev
```

脚本只升级通过题目的认证版本；未通过题目变为 `stale` 并形成替换缺口，不覆盖题目内容或历史答题记录。

重置会删除 MySQL、Chroma 和前端依赖卷，必须输入 `RESET` 二次确认：

```powershell
./scripts/demo.ps1 reset
```

代码质量与离线评测建议在容器内执行：

```powershell
docker compose exec backend python -m ruff check app tests
docker compose exec backend python -m compileall -q app tests
docker compose exec backend python -m pytest -q
docker compose exec backend python -m app.scripts.evaluate_rag --split development --live --json
```

真实 `--live` 评测会调用外部 embedding/模型服务，应仅在已获得授权且需要刷新评测基线时运行。
