# RAG 专项评测数据

本目录只用于 Knowledge Retrieval Agent 的离线专项评测，不会被
`test_script/evaluate.py` 的端到端 P0 评测加载。

- `development_cases.json`：30 条开发案例，可用于算法调试和权重调整。
- `acceptance_cases.json`：20 条冻结验收案例，不得按案例调参。
- `manifest.json`：固定知识数据版本和验收集规范化内容哈希。

运行校验：

```powershell
cd backend
python -m app.scripts.validate_rag_evaluation --json
```

记录当前确定性哈希检索基线：

```powershell
python -m app.scripts.evaluate_rag --engine legacy-hash --split all --json
```
