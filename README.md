# 天使记忆 (Angel Memory) — NekroAgent 插件

[`astrbot_plugin_angel_memory`](https://github.com/kawayiYokami/astrbot_plugin_angel_memory) 的原生 NekroAgent 移植版本。
无需 AstrBot 或 Angel Heart。本移植使用 NekroAgent 的生命周期钩子、提示词注入、沙盒方法、模型组、频道历史和认证插件路由。

## 功能

- `angel_remember`：存储持久的事实、偏好、承诺、关系和可复用经验。
- `angel_recall`：搜索频道记忆和结构化笔记。
- `angel_note_read`：通过稳定的 `N<数字>` 标识符读取笔记。
- `angel_note_create`：创建持久的结构化知识笔记。
- 自动提示词回忆：自动注入相关的频道和用户记忆。
- 可选的 LLM 记忆整合：使用配置的 NekroAgent 模型组。
- 用户画像和四个可调节的灵魂状态维度。
- 维护、归档、JSON 导入/导出和 AstrBot 迁移工具。
- SQLite FTS5 检索，支持中文字符和二元组归一化。

## 安装

将完整的 `nekro_plugin_angel_memory` 目录复制到 NekroAgent 工作插件目录：

```text
nekro-agent/
└── plugins/
    └── nekro_plugin_angel_memory/
        ├── __init__.py
        ├── plugin.py
        ├── main.py
        ├── engine.py
        ├── storage.py
        └── ...
```

重启 NekroAgent，然后在插件管理页面启用并配置「天使记忆」。本插件无额外 Python 包依赖。

## 数据存储位置

运行时数据存储在 NekroAgent 原生插件路径下：

```text
NEKRO_DATA_DIR/plugin_data/luoxiQAQ.nekro_plugin_angel_memory/
```

SQLite 数据库为该目录下的 `angel_memory.sqlite3`。

## 主要配置

- `ENABLE_AUTO_RECALL`：将相关历史证据注入提示词。
- `AUTO_RECALL_LIMIT`：灵魂状态缩放前的最大自动记忆命中数。
- `PROMPT_MAX_CHARS`：注入记忆提示词的字符硬限制。
- `ENABLE_AUTO_CONSOLIDATION`：使用 LLM 定期提取持久记忆。
- `CONSOLIDATE_EVERY_USER_MESSAGES`：整合触发的用户消息间隔。
- `CONSOLIDATION_MODEL_GROUP`：可选模型组；留空使用频道模型组。
- `ENABLE_HEURISTIC_REMEMBER`：记住中文"记住这个"等明确要求。
- `ENABLE_USER_PROFILE`：维护每频道用户画像。
- `ENABLE_SOUL_STATE`：启用回忆和表达倾向状态。

如果同时启用了 NekroAgent 内置记忆系统，两个系统可能会注入重叠的上下文。
建议禁用其中一个或减少回忆数量限制以避免提示词重复。

## 管理 API

NekroAgent 将认证插件路由挂载在：

```text
/plugins/luoxiQAQ.nekro_plugin_angel_memory
```

以下端点需要 NekroAgent 管理员会话：

- `GET /status`
- `GET /memories?chat_key=...`
- `PATCH /memories/{id}`
- `DELETE /memories/{id}`
- `GET /notes?chat_key=...`
- `DELETE /notes/{id}`
- `POST /consolidate?chat_key=...`
- `POST /maintenance`
- `GET /export`
- `POST /import`

## AstrBot 迁移

导出原始插件数据为 JSON，或指向兼容的 SQLite 数据库，然后在 NekroAgent 仓库根目录运行：

```bash
python -m plugins.nekro_plugin_angel_memory.migrate_astrbot \
  /path/to/angel-memory-backup.json \
  /path/to/nekro-data/plugin_data/luoxiQAQ.nekro_plugin_angel_memory/angel_memory.sqlite3 \
  --chat-key onebot_v11-group_123456
```

AstrBot 作用域不一定能直接映射到 NekroAgent 的 `chat_key`。
当源记录不包含正确的目标作用域时，请提供 `--chat-key` 参数。
迁移前请备份源和目标数据库。

## 安全性

- 整合提示词明确排除密码、凭据和密钥。
- 自动和 Agent 工具创建的记忆会拒绝明显的凭据和私钥。
- 回忆的内容标记为历史证据，不是当前指令。
- 请确保插件 API 在 NekroAgent 认证和 HTTPS 之后。
- 共享导出数据前请检查内容，可能包含个人历史。

## 兼容性说明

这是一个功能性的原生移植，不是逐字节的复制。原始的独立 WebUI、Tantivy 索引、
FAISS/向量嵌入和重排序器已替换为 NekroAgent 原生 API 和轻量级 SQLite FTS5 检索。

## 许可证

本移植保留了原始项目的 GNU GPL v3 许可和署名。
完整许可证文本见 `LICENSE`，署名信息见 `NOTICE`。