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
- 好感度关系层：按频道维护用户好感度、阶段、标签与变动记录，注入当前发言人的关系卡。
- 好感度门槛门控：记忆可设 `min_favor`，关系没到就不会被讲出来（只会进「暂时不想细说的事」）。
- 好感度排行榜卡片：`查看好感度` 直接出一张排行榜图片。
- 维护、归档、JSON 导入/导出和 AstrBot 迁移工具。
- SQLite FTS5 检索，支持中文字符和二元组归一化。

## 安装

将完整的 `nekro_memory_angel` 目录复制到 NekroAgent 工作插件目录：

```text
nekro-agent/
└── plugins/
    └── nekro_memory_angel/
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
NEKRO_DATA_DIR/plugin_data/luoxiQAQ.nekro_memory_angel/
```

SQLite 数据库为该目录下的 `angel_memory.sqlite3`，包含 `memories`、`notes`、`user_profiles`、
`soul_states`、`favorability`、`favorability_events`、`state` 以及两张 FTS5 索引表。
排行榜卡片的缓存图与头像在 `cache/` 子目录下。

排行榜卡片为 1280 宽双列布局，含金/银/铜名次徽章、圆形头像、进度条与阶段标签；
分数配色遵循中文习惯的「涨红跌绿」——正分红、负分绿、零分灰。

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
- `ENABLE_FAVORABILITY`：启用好感度关系层。
- `ENABLE_FAVOR_GATING`：好感度门槛门控记忆（记忆上的 `min_favor` 生效）。
- `FAVOR_MAX_ABS_SCORE`：好感度绝对值上限（默认 ±100）。
- `FAVOR_MAX_SINGLE_DELTA` / `FAVOR_MIN_INTERVAL_MINUTES` / `FAVOR_MAX_DAILY_GAIN` / `FAVOR_MAX_DAILY_LOSS`：防刷分约束。
- `FAVOR_MARGINAL_DECAY` / `FAVOR_REQUIRE_CONCRETE_REASON`：边际递减与「理由必须具体」。
- `FAVOR_DECAY_*` / `FAVOR_RECOVER_*`：长时间不互动的降温与负分回升。
- `FAVOR_RANK_CARD_ENABLED` / `FAVOR_RANK_LIMIT` / `FAVOR_RANK_CARD_FONT` / `FAVOR_RANK_AVATAR`：排行榜卡片。
- `WEBUI_ACCESS_KEY`：好感度管理页的免登录访问密钥（留空则只能用 NekroAgent 管理员身份访问）。
- `CLEAR_MEMORY_ON_CHANNEL_RESET`：开启后，在面板重置频道会同时清除该频道的全部记忆、笔记、画像、灵魂状态与好感度（默认关闭，长期记忆跨频道重置保留）。

如果同时启用了 NekroAgent 内置记忆系统，两个系统可能会注入重叠的上下文。
建议禁用其中一个或减少回忆数量限制以避免提示词重复。

## 管理 API

NekroAgent 将认证插件路由挂载在：

```text
/plugins/luoxiQAQ.nekro_memory_angel
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
- `POST /reset`：清除数据。带 `?chat_key=...` 时只清除该频道的记忆、笔记、画像与灵魂状态；不带参数则清空全部数据（含内部状态）。操作不可恢复，执行前建议先 `GET /export` 备份。
- `GET /export`
- `POST /import`

好感度相关端点（管理员会话，或在配置了 `WEBUI_ACCESS_KEY` 后带 `?key=xxx`）：

- `GET /favor?chat_key=...`：列出该频道的好感度档案（含阶段）
- `GET /favor/events?chat_key=...&user_id=...`：查看某用户的变动记录
- `POST /favor`：新增/调整档案（`score` 直接重设，或 `delta` 增量调整）
- `DELETE /favor?chat_key=...&user_id=...`：删除档案
- `POST /favor/decay`、`POST /favor/recover`：手动结算衰减 / 回升
- `GET /favor/card?chat_key=...`：直接返回排行榜卡片 PNG
- `GET /ui`：好感度管理页（浏览器打开即可改分、删档、看卡片）

## 好感度与解锁门控

好感度是「长期关系」而不是当前情绪，按 **频道 + 用户** 维度维护。

### 阶段

| 分数区间 | 阶段 | 互动指引 |
|---|---|---|
| ≤ -60 | 排斥 | 保持距离，谨慎回应，必要时明确边界。 |
| -60 ~ -20 | 保留 | 维持礼貌但克制，先观察，不要过度投入。 |
| -20 ~ 20 | 中立 | 正常友好互动，不主动施加亲密语气。 |
| 20 ~ 60 | 亲近 | 可以更自然、更积极地回应，适度体现熟悉感。 |
| 60 ~ 85 | 偏爱 | 可明显更热情，主动照顾对方体验并记住其偏好。 |
| ≥ 85 | 特别亲密 | 可使用显著亲密与偏爱语气，但仍需遵守角色边界。 |

### 记忆门槛（min_favor）

每条记忆可以带 `min_favor`：`0=公开 / 20=亲近 / 60=偏爱`。
发言人好感度没到门槛时，这条记忆**不会**进正文，只会以标题形式出现在「#暂时不想细说的事」里，
让角色可以自然带过而不是生硬拒绝。关闭 `ENABLE_FAVOR_GATING` 即恢复为无条件注入。

### 防刷分约束

单次调整上限、同一用户最小调整间隔、每日净加/净扣上限、边际递减（≥60 折半、≥85 折至 30%），
以及「理由必须是具体行为」——只有氛围词（喜欢/开心/不错…）时不予加分。
被拦下时工具会返回明确原因，不会静默生效。

### LLM 工具

| 工具 | 类型 | 作用 |
|---|---|---|
| `调整好感度` | BEHAVIOR | 按具体行为增减关系分并记录证据（受全部约束层限制） |
| `重设好感度档案` | BEHAVIOR | 直接重写档案（初始化 / 大幅修正），不动其他档案 |
| `删除好感度档案` | BEHAVIOR | 删除某用户档案 |
| `查看好感度档案` | AGENT | 查看某用户的完整档案 |
| `列出好感度档案` | AGENT | 列出本频道档案摘要 |
| `结算好感度衰减` | AGENT | 手动跑一次降温结算 |
| `结算好感度回升` | AGENT | 手动跑一次负分回升 |

`angel_remember` 新增 `min_favor` 参数；`angel_recall` 会自动按当前发言人的好感度门控结果。

### 群聊命令

| 命令 | 别名 | 权限 | 说明 |
|---|---|---|---|
| `查看好感度` | 好感度排行 / 好感榜 / favor_rank | 用户 | 本频道好感度排行榜（图片，失败回退文本） |
| `好感度档案` | favor_status / fvs | 用户 | 查看自己（或指定用户）的档案 |
| `好感度加分` | favor_add | 超管 | `好感度加分 <用户ID> <分值>` |
| `好感度扣分` | favor_sub | 超管 | `好感度扣分 <用户ID> <分值>` |
| `好感度设定` | favor_set | 超管 | `好感度设定 <用户ID> <分数>` |
| `好感度删除` | favor_remove | 超管 | `好感度删除 <用户ID>` |

排行榜卡片依赖 Pillow 与可用的中文字体；缺少任一时自动回退纯文本，不影响其他功能。
`FAVOR_RANK_CARD_FONT` 可显式指定中文字体路径，留空则自动探测（Noto Sans CJK / 微软雅黑 / 苹方）。

## 数据重置说明

NekroAgent 插件管理页的「重置数据」按钮只会删除插件存储（`plugin_data` 表）中的键值数据，
**不会删除插件数据目录中的文件**。本插件的所有记忆都保存在独立的 SQLite 数据库
`angel_memory.sqlite3` 中，因此点击该按钮无法清除记忆，这是框架行为，并非本插件数据残留。

如需真正清除记忆，请使用以下任一方式：

- 调用管理 API：`POST /plugins/luoxiQAQ.nekro_memory_angel/reset` 清空全部数据，
  或 `POST /plugins/luoxiQAQ.nekro_memory_angel/reset?chat_key=<频道ID>` 只清除单个频道。
- 在插件配置中开启 `CLEAR_MEMORY_ON_CHANNEL_RESET` 后，于面板「重置频道」即可同步清除该频道的记忆。
- 彻底重置可停止 NekroAgent 后删除 `NEKRO_DATA_DIR/plugin_data/luoxiQAQ.nekro_memory_angel/` 目录。

## AstrBot 迁移

导出原始插件数据为 JSON，或指向兼容的 SQLite 数据库，然后在 NekroAgent 仓库根目录运行：

```bash
python -m plugins.nekro_memory_angel.migrate_astrbot \
  /path/to/angel-memory-backup.json \
  /path/to/nekro-data/plugin_data/luoxiQAQ.nekro_memory_angel/angel_memory.sqlite3 \
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