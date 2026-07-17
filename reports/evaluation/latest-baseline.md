# BASELINE 可复现评测报告

- 状态：passed
- 案例：50/50
- 知识库版本：ai_app_dev-kb-2026.07
- 脚本版本：live-evaluator-2.0
- 评测时间：2026-07-17T06:47:13.638410+00:00
- 运行模式：baseline
- 运行编号：baseline

| 指标 | 分子 | 分母 | 比率 |
|---|---:|---:|---:|
| 幻觉率 | 2 | 200 | 0.01 |
| 难度匹配准确率 | 44 | 50 | 0.88 |
| 核心知识覆盖率 | 96 | 100 | 0.96 |
| 审核结论准确率 | 50 | 50 | 1.0 |
| 画像结论准确率 | 50 | 50 | 1.0 |

性能：P50 3875 ms，P95 5701 ms。

## 失败案例

- hallucination: EVAL-007, EVAL-031
- difficulty: EVAL-006, EVAL-013, EVAL-020, EVAL-027, EVAL-034, EVAL-041
- coverage: EVAL-009, EVAL-019, EVAL-029, EVAL-039
- review_decision: 无
- profile_decision: 无

无法判定：Cases without a determinable observed result are excluded from metric denominators.
