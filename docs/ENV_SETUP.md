# 环境配置

## 必需环境变量

参考根目录 `.env.example`。

- `DATABASE_URL`: MySQL 连接字符串
- `CHROMA_HOST`: ChromaDB 独立服务地址（Docker 内为 `chromadb`）
- `CHROMA_PORT`: ChromaDB 服务端口（Docker 内为 `8000`）
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
