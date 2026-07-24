# RAG Legacy Hash Baseline

- 状态：baseline_recorded
- 数据集：all（50 条）
- Embedding：mock-deterministic-embedding
- 算法版本：legacy-hash-baseline-1.0
- 知识数据版本：`sha256:837441b02400435bf83fc802d79b69a473b591fdd9062529e16154c22560c608`
- 冻结验收哈希：`sha256:25ce6ac9c25158a88cb7eb92d0068bec769331714bfd53a87d39c9900157d589`
- 评测时间：2026-07-24T03:44:22.324423+00:00

| 指标 | 分子 | 分母 | 比率 | 后续 V2 目标 |
|---|---:|---:|---:|---:|
| recall_at_12 | 76 | 111 | 0.684685 | >= 90% |
| priority_top_12_coverage | 33 | 37 | 0.891892 | >= 95% |
| prerequisite_coverage | 14 | 30 | 0.466667 | >= 90% |
| source_completeness | 588 | 588 | 1.0 | = 100% |

- 跨领域错误：0
- 延迟：P50 1.913 ms，P95 3.145 ms
- V2 契约非法输出：不适用（本报告记录 V1 legacy-hash 输出）。

> 本报告是旧哈希检索的对照基线。未达到未来 V2 门槛不代表本次数据切片失败。
