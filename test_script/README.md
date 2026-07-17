# 可复现评测

`data/evaluation_cases/*.json` 是唯一事实来源。运行：

```powershell
python test_script/evaluate.py --xlsx
```

该命令生成 baseline 报告。案例文件中的 `observed_result` 只是可复现基准，不代表真实模型结果。

真实模型必须按顺序运行：

```powershell
python test_script/run_live.py --stage smoke
python test_script/run_live.py --stage regression
python test_script/run_live.py --stage formal --xlsx
```

运行前必须配置三个真实模型并设置 `ALLOW_FIXTURE_LLM=false`。live runner 通过 `/api/v1` 创建任务、等待任务终态、读取脱敏 Agent 运行记录，并将原始运行证据保存到 `reports/evaluation/runs/{run_id}.json`。

脚本会校验案例唯一性，计算幻觉率、难度匹配、核心知识覆盖、审核/画像结论准确率及任务和 Agent P50/P95，并输出：

- `reports/evaluation/latest.json`
- `reports/evaluation/latest.md`
- `reports/evaluation/latest.xlsx`（使用 `--xlsx` 时）
- `reports/evaluation/latest-live.json`
- `reports/evaluation/latest-live.md`
- `reports/evaluation/latest-live.xlsx`（正式运行使用 `--xlsx` 时）

每项比例均保留分子、分母、失败案例 ID 和无法判定声明。
