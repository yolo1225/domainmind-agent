# 智能制造可执行测试数据包

本目录用于从空库复现比赛第二领域 `smart_manufacturing`。它包含数据库切片、三类脱敏学情以及受管的三案例运行输入；不包含 50 例离线评测案例，也不声明第二领域质量指标。

## 使用方式

1. 运行 `scripts/submission-fixture.ps1 verify -FixtureDir data/submission_fixtures/smart_manufacturing_v1` 校验哈希和内容。
2. 在新的 Docker 卷或已清空数据库中运行 `scripts/submission-fixture.ps1 bootstrap -FixtureDir data/submission_fixtures/smart_manufacturing_v1`。脚本不会清空现有数据。
3. 若需与主演示环境隔离，可添加 `-ComposeProject cognivia_sm_test -ComposeFile docker-compose.submission.yml`。
4. 构建索引后运行 `python test_script/smart_manufacturing_demo_acceptance.py --base-url http://localhost:18000/api/v1`，生成脱敏案例与报告。
5. `import_source/` 中的 Markdown、同目录的 XLSX 与启动夹具互斥，不能在同一数据库叠加导入。

## 内容

- 67 条可追溯知识条目与课程规则生成的 `next_step` 图谱关系。
- 402 道活动正式题：67 道诊断题、201 道分阶测验题、134 道掌握检查题。
- 初学者、中阶和高阶三份合成画像及学习路径；所有账号均标记为测试数据。
- `manual_demo_cases.json`：三组真实运行的受管输入与预期业务断言。
- `import_source/` 内的 Markdown/XLSX 是已配对的前端手动导入材料；`source_assets/` 仅保留上游来源副本。
