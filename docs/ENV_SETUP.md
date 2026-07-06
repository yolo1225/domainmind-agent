# 环境配置

## 必需环境变量

参考根目录 `.env.example`。

- `DATABASE_URL`: MySQL 连接字符串
- `CHROMA_PERSIST_DIRECTORY`: ChromaDB 本地持久化目录
- `OPENAI_API_BASE`: OpenAI 兼容模型服务地址
- `OPENAI_API_KEY`: 模型服务密钥
- `PRIMARY_LLM_MODEL`: 主生成模型
- `PRIMARY_REVIEW_MODEL`: 主审核模型
- `SECONDARY_REVIEW_MODEL`: 次审核模型
- `EMBEDDING_MODEL`: Embedding 模型

## 本地目录

- `data/chroma`: ChromaDB 持久化目录
- `data/seed`: 领域包和种子数据
- `storage/exports`: 报告导出目录
