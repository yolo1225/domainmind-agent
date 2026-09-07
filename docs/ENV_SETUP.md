# 环境配置

## 可视化模型配置

模型接入信息不必再手动编辑 `.env`。以管理员账号登录后，进入左侧「管理与质量 → 模型配置」页面，可可视化编辑：

- `OPENAI_API_BASE`：API 地址
- `OPENAI_API_KEY`：API Key（数据库中加密存储，接口不回显明文）
- `PRIMARY_LLM_MODEL` / `PRIMARY_REVIEW_MODEL` / `SECONDARY_REVIEW_MODEL`：生成与双审核模型
- `EMBEDDING_MODEL`：Embedding 模型

保存后写入数据库并立即生效，重启后也从数据库恢复；运行中的服务不直接改写 `.env`。

### 首次启动（可延后向量化）

`start.bat`（完整比赛夹具）和 `./scripts/demo.ps1 start`（开发种子）在缺少模型配置时都会**跳过候选索引向量化并给出警告**，前端照常启动。此时按下面顺序完成配置即可：

1. 管理员登录，进入「管理与质量 → 模型配置」页，填写并保存模型 6 项。
2. 宿主机执行 `./scripts/demo.ps1 rebuild-index` 重建候选索引。
3. `./scripts/demo.ps1 verify` 确认 `rag.ready=true`、`ready_for_live_demo=true`。

如需把模型配置同步回根目录 `.env`（例如 `down -v` 重置前作为兜底），执行：

```powershell
./scripts/sync-model-env.ps1
```

其余超时、并发等高级参数仍通过 `.env` 控制。

## 必需环境变量

参考根目录 `.env.example`。下面两类里，**基础设施必须先在 `.env` 配好**，模型 6 项可留空、改走可视化页面。

基础设施（必需）：

- `DATABASE_URL`: MySQL 连接字符串
- `CHROMA_HOST`: ChromaDB 独立服务地址（Docker 内为 `chromadb`）
- `CHROMA_PORT`: ChromaDB 服务端口（Docker 内为 `8000`）
- `REDIS_URL`、`JWT_SECRET_KEY`、`INITIAL_ADMIN_*` 等登录与加密所需项

模型（可选，可走 UI）：

- `OPENAI_API_BASE`: OpenAI 兼容模型服务地址
- `OPENAI_API_KEY`: 模型服务密钥
- `PRIMARY_LLM_MODEL`: 主生成模型
- `PRIMARY_REVIEW_MODEL`: 主审核模型
- `SECONDARY_REVIEW_MODEL`: 次审核模型
- `EMBEDDING_MODEL`: Embedding 模型
- `ALLOW_FIXTURE_LLM`: 仅本地/测试可设为 `true`；`APP_ENV=production` 时强制要求真实模型配置

正式演示示例：

```env
OPENAI_API_BASE=https://your-provider.example/v1
OPENAI_API_KEY=your-secret-key
PRIMARY_LLM_MODEL=your-generation-model
PRIMARY_REVIEW_MODEL=your-primary-review-model
SECONDARY_REVIEW_MODEL=your-secondary-review-model
ALLOW_FIXTURE_LLM=false
```

两个审核模型名必须不同。`GET /api/v1/health/dependencies` 只显示是否配置和模型名，不显示密钥；只有 `ready_for_live_demo=true` 才能运行 live 评测。

## 数据与导出目录

- `data/seed`: 领域包和种子数据
- `storage/exports`: 学习资源导出目录
- `reports/evaluation`: 离线评测报告目录

ChromaDB 固定作为 Docker 独立服务运行，持久化数据由 Compose 的 `chroma_data` volume 管理；`data/chroma` 不是运行目录。
