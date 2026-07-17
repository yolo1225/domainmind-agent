# Docker 演示操作手册

## 1. 启动与检查

1. 从 `.env.example` 复制 `.env`，填写接口地址、密钥和三个模型名。
2. 保持 `ALLOW_FIXTURE_LLM=false`。
3. 运行 `./scripts/demo.ps1 start`。
4. 运行 `./scripts/demo.ps1 verify`，确认 `live_models_ready=True`、知识点 50、诊断题 60。
5. 打开 http://localhost:5173/ 和 http://localhost:8000/docs。

## 2. 真实模型评测

依次执行：

```powershell
python test_script/run_live.py --stage smoke
python test_script/run_live.py --stage regression
python test_script/run_live.py --stage formal --xlsx
```

每个任务必须在 Agent 运行记录中出现 `provider_mode=live`。报告输出到 `reports/evaluation`，原始运行证据输出到 `reports/evaluation/runs`。

## 3. 七分支验收

运行以下命令会产生真实模型费用：

```powershell
python test_script/demo_acceptance.py
```

脚本依次检查首次生成、仅解释不更新、多轮证据更新画像、错误复核、挑战任务、两轮修订失败、双模型冲突与原线程人工恢复。结果输出到 `reports/demo/latest.json` 和 `reports/demo/latest.md`。

后两个异常分支取决于真实模型输出。如果现场无法稳定复现，可传入历史真实快照：

```powershell
python test_script/demo_acceptance.py --snapshot reports/demo/live-exception-snapshot.json
```

快照的 `revision_exhausted`、`manual_review_resume` 项必须包含 `task_id`、`recorded_at`、`model_names` 和 `provider_mode=live`。脚本拒绝未标识或 fixture 快照。

## 4. 10 分钟展示顺序

1. 诊断与三类画像，1 分钟。
2. 启动生成任务并观察八节点协作图，2 分钟。
3. 查看三类资源、来源和双模型审核，2 分钟。
4. 演示导学消息、画像不更新和证据充分更新，2 分钟。
5. 展示人工复核、版本和导出，1.5 分钟。
6. 展示知识增量重建以及 live 评测 P50/P95，1.5 分钟。

## 5. 故障处理

- `ready_for_live_demo=false`：检查五个模型环境变量和 `ALLOW_FIXTURE_LLM`。
- Chroma 异常：执行 `docker compose restart chromadb backend`，再运行知识索引重建。
- 数据不完整：执行 `./scripts/demo.ps1 reset`，输入 `RESET` 后重新初始化。
- 5173 被占用：停止本机 Vite 服务，避免与 Docker 前端同时运行。
