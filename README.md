# 天使记忆 (Angel Memory) — NekroAgent 插件

[`astrbot_plugin_angel_memory`](https://github.com/kawayiYokami/astrbot_plugin_angel_memory) 的原生 NekroAgent 移植版本。
无需 AstrBot 或 Angel Heart。本移植使用 NekroAgent 的生命周期钩子、提示词注入、沙盒方法、模型组、频道历史和认证插件路由。

## 功能

- `angel_remember`：存储持久的事实、偏好、承诺、关系和可复用经验。
- `angel_recall`：搜索频道记忆和结构化笔记。
- `angel_note_read`：通过稳定的 `N<数字>` 标识符读取笔记。
- `angel_note_create`：创建持久的结构化知识笔记。
- `记住事实` / `查看事实` / `删除事实`：把「谁·什么属性·什么值」结构化持久化，按需检索而不是反复塞进上下文。
- 分层记忆：短期滑动窗口（不落库）→ 滚动摘要 → 结构化事实 → 长期记忆 → 画像/灵魂状态。
- 分层预算注入：各层按权重分配字符预算，超出即截断，不会一股脑全塞进提示词。
- 自动提示词回忆：自动注入相关的频道和用户记忆。
- 可选的 LLM 记忆整合：使用配置的 NekroAgent 模型组，同时抽取记忆、事实与滚动摘要。
- 用户画像和四个可调节的灵魂状态维度。
- 关系状态机：按频道维护用户关系**阶段**，由**关系事件**驱动跃迁，而不是纯数值加减。
- 聊过就进榜：用户首次发言即建一条「中立、零证据」的档案，排行榜立刻有花名册；
  **阶段跃迁仍然只由关系事件驱动**，所以这只是花名册，不改变状态机语义（`FAVOR_AUTO_ENROLL`）。
- 关系门槛门控：记忆可设 `min_favor`，关系没到就不会被讲出来（只会进「暂时不想细说的事」）。
- 好感度排行榜卡片：`/查看好感度` 直接出一张排行榜图片；群里不带 `/` 直接发 `查看好感度` 也认。
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
`soul_states`、`facts`（结构化事实）、`digests`（滚动摘要）、`favorability`、`favorability_events`、
`state` 以及两张 FTS5 索引表。排行榜卡片的缓存图与头像在 `cache/` 子目录下。

排行榜卡片为 1280 宽双列布局，含金/银/铜名次徽章、圆形头像、进度条与阶段标签；
阶段配色遵循中文习惯的「涨红跌绿」——正面阶段红、负面阶段绿、中立灰。
进度条反映的是「阶段 + 阶段内证据进度」，不是裸分数。

### 卡片为什么要往 `uploads/` 里再放一份

渲染好的卡片先落在插件数据目录（`cache/favor_rank/`，管理 API 的 `GET /favor/card` 直接读它），
但**这条路径发不进群**：Nekro 的消息管线只认路径里含 `uploads` / `shared` 段的「沙盒路径」，
会把 `/app/uploads/<相对>` 还原成 `<NEKRO_DATA_DIR>/uploads/<清洗后的 chat_key>/<相对>`；
直接把 `plugin_data/...` 交给它就会抛

```text
Unable to detect path location for: .../plugin_data/luoxiQAQ.nekro_memory_angel/cache/favor_rank/xxx.png,
make sure your path is valid shared path or upload path
```

并且这个报错会被当成**文本消息发到群里**（而不是静默失败），所以看起来像机器人在刷错误日志。
因此不带 `/` 的关键词入口（`查看好感度`）会先把卡片复制一份到

```text
<NEKRO_DATA_DIR>/uploads/<清洗后的 chat_key>/favor_rank/favor_rank_<md5(chat_key)[:10]>.png
```

再以 `/app/uploads/favor_rank/<文件名>` 交给消息管线。复制失败时自动降级为文字排行榜，
不会把异常文本发进群。带 `/` 的命令入口不用手动复制 —— 框架的
`materialize_command_response` 会把命令输出的图片自行复制进 `uploads/`。

### 为什么关键词入口只发图片、不发那行文字

两条入口的发送通道不同，形态天然不一致：

| 入口 | 通道 | 前缀 | 消息条数 |
| --- | --- | --- | --- |
| `/查看好感度` | 框架命令系统 → `build_command_output_platform_segments` → `forward_message` | 文本被加上 `AI_COMMAND_OUTPUT_PREFIX`（默认 `≡NA≡:`） | 图文**合并**为一条 |
| `查看好感度` | 插件钩子直发 `send_text` / `send_image` | 无 | 文字、图片各一条 |

`≡NA≡:` 是框架用来标识「这是命令输出」的标记，同时也在 `AI_IGNORED_PREFIXES` 里 ——
带此前缀的消息不会被 AI 参考、也不会触发 AI 回复，目的是让命令输出不污染上下文。
插件直发通道拿不到这个前缀，也无法把文本和图片合并成一条。

为了不让同一个功能看起来像两个不同的东西，关键词入口在**成功出图时只发卡片图片**，
不再单独发一行「本频道好感度排行榜（共 N 人）」—— 人数在卡片列表里一眼可见，信息没丢。
只有降级路径（功能关闭 / 无数据 / 渲染失败 / 复制失败）仍然发文字，因为那时没有图可发。

## 记忆分层

| 层 | 载体 | 生命周期 | 注入方式 |
|---|---|---|---|
| L0 短期 | 最近 N 条原始对话（滑动窗口） | 每轮重建，不落库 | `[最近对话]`，按条数截断 |
| L1 中期 | `digests` 滚动摘要 | 每次整合滚动写入 | `[近期梗概]` |
| L2 事实 | `facts` 结构化 KV | 幂等 upsert，长期持久 | `[关键事实]`，按用户 + 关键词取用 |
| L3 长期 | `memories` 语义/情景/偏好/承诺 | 长期持久，可归档 | `[长期记忆]`，FTS 检索 + 关系门槛门控 |
| L4 画像 | `user_profiles` + `soul_states` | 长期持久 | `[用户画像]` / `[灵魂状态]` |

每层按 `PROMPT_BUDGET_*` 权重分配 `PROMPT_MAX_CHARS` 的字符预算，超出预算的部分会被截断并标注
`…（本层内容已按预算截断）`。开启 `RESPECT_UPSTREAM_MEMORY` 时，检测到 NekroAgent 自带记忆系统
（`MEMORY_ENABLE_SYSTEM`）在运行会把本插件总预算压缩到 60%，避免两套记忆互相挤占上下文。

## 主要配置

- `ENABLE_AUTO_RECALL`：将相关历史证据注入提示词。
- `AUTO_RECALL_LIMIT`：灵魂状态缩放前的最大自动记忆命中数。
- `PROMPT_MAX_CHARS`：所有记忆分层的字符总预算（按下面各层权重切分）。
- `ENABLE_SLIDING_WINDOW` / `SLIDING_WINDOW_MESSAGES` / `SLIDING_WINDOW_MSG_CHARS`：短期滑动窗口。
- `ENABLE_FACTS` / `FACT_PROMPT_LIMIT` / `FACT_MAX_PER_CONSOLIDATION`：结构化事实层。
- `ENABLE_DIGEST` / `DIGEST_PROMPT_LIMIT` / `DIGEST_MAX_CHARS`：滚动摘要层。
- `PROMPT_BUDGET_WINDOW` / `_FACTS` / `_MEMORIES` / `_DIGEST` / `_RELATION` / `_SOUL`：各层预算权重。
- `RESPECT_UPSTREAM_MEMORY`：上游记忆系统开启时自动压缩本插件预算。
- `ENABLE_AUTO_CONSOLIDATION`：使用 LLM 定期提取持久记忆。
- `CONSOLIDATE_EVERY_USER_MESSAGES`：整合触发的用户消息间隔。
- `CONSOLIDATION_MODEL_GROUP`：可选模型组；留空使用频道模型组。
- `ENABLE_HEURISTIC_REMEMBER`：记住中文"记住这个"等明确要求。
- `ENABLE_USER_PROFILE`：维护每频道用户画像。
- `ENABLE_SOUL_STATE`：启用回忆和表达倾向状态。
- `ENABLE_FAVORABILITY`：启用关系状态机。
- `ENABLE_FAVOR_GATING`：关系门槛门控记忆（记忆上的 `min_favor` 生效）。
- `FAVOR_DEFAULT_STAGE`：新档案默认阶段（默认「中立」）。
- `FAVOR_AUTO_ENROLL`：**聊过就进榜**（默认开）。开启后首次发言即建档，阶段仍是「中立」零证据；
  关闭则回到纯事件制——只有被记录过关系事件的人才有档案，榜单可能长期为空。
- `FAVOR_EXPOSE_NUMBERS`：是否把内部证据权重/展示分写进提示词（默认关闭）。
- `FAVOR_MIN_INTERVAL_MINUTES` / `FAVOR_MAX_EVENTS_PER_DAY` / `FAVOR_MAX_POSITIVE_PER_DAY` / `FAVOR_MAX_NEGATIVE_PER_DAY`：事件频率与每日上限。
- `FAVOR_REPEAT_DECAY` / `FAVOR_STAGE_MIN_KINDS`：同类型事件边际递减、升级所需事件种类数。
- `FAVOR_EVIDENCE_HALF_LIFE_HOURS` / `FAVOR_ERODE_INTERVAL_HOURS`：证据半衰期与衰减结算间隔。
- `FAVOR_REQUIRE_CONCRETE_EVIDENCE`：证据必须是具体行为（只有氛围词时不予记录）。
- `FAVOR_MAX_ABS_SCORE`：展示分绝对值上限（仅用于排序展示，不是权威状态）。
- `FAVOR_MAX_EVENT_HISTORY` / `FAVOR_PROMPT_EVENT_LIMIT` / `FAVOR_GROUP_OVERVIEW_LIMIT` / `FAVOR_MAX_TAGS`：事件流水保留条数、提示词中展示的最近事件数、无触发用户时的关系摘要数、关系标签上限。
- `FAVOR_RANK_CARD_ENABLED` / `FAVOR_RANK_LIMIT` / `FAVOR_RANK_HIDE_EMPTY` / `FAVOR_RANK_CARD_FONT` / `FAVOR_RANK_AVATAR`：排行榜卡片。
- `FAVOR_RANK_KEYWORD_ENABLED` / `FAVOR_RANK_KEYWORDS`：无前缀关键词触发排行榜（默认开，词表 `查看好感度,好感榜`）。
- `WEBUI_ACCESS_KEY`：好感度管理页的免登录访问密钥（留空则只能用 NekroAgent 管理员身份访问）。
- `CLEAR_MEMORY_ON_CHANNEL_RESET`：开启后，在面板重置频道会同时清除该频道的全部记忆、笔记、画像、事实、摘要、灵魂状态与关系档案（默认关闭，长期记忆跨频道重置保留）。

如果同时启用了 NekroAgent 内置记忆系统（`MEMORY_ENABLE_SYSTEM`），两个系统会注入重叠的上下文。
本插件默认开启 `RESPECT_UPSTREAM_MEMORY`：检测到上游记忆系统在跑时自动把自身注入预算压缩到 60%。
如果仍然觉得提示词冗余，可以进一步调低 `PROMPT_BUDGET_*` 权重、减少 `AUTO_RECALL_LIMIT`，
或直接关闭其中一个系统。

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

- `GET /favor?chat_key=...`：列出该频道的关系档案（含阶段、阶段内证据、事件数）
- `GET /favor/events?chat_key=...&user_id=...`：查看某用户的关系事件流水
- `POST /favor`：`{"stage": "亲近"}` 人工设定阶段；或 `{"kind": "help", "evidence": "...", "severity": 2}` 记录关系事件
- `DELETE /favor?chat_key=...&user_id=...`：删除档案与事件历史
- `POST /favor/erode`：手动结算证据衰减与长期无互动回落（`/favor/decay`、`/favor/recover` 为兼容别名）
- `GET /facts?chat_key=...&user_id=...&query=...` / `DELETE /facts?chat_key=...&fact_id=...`：结构化事实
- `GET /favor/card?chat_key=...`：直接返回排行榜卡片 PNG
- `GET /ui`：关系管理页（浏览器打开即可设定阶段、记录事件、删档、看卡片）

## 关系状态机

关系是「长期阶段」而不是当前情绪，按 **频道 + 用户** 维度维护。权威状态是
**阶段 + 阶段内证据累积**，`score` 只是从二者投影出来的展示值（用于排行榜排序与记忆门槛）。

### 事件驱动

一切变化都来自**关系事件**：事件有类型、极性、严重度和具体证据。

| 方向 | 事件类型 |
|---|---|
| 正向 | `help` 主动帮忙 · `insight` 有价值观点 · `support` 情绪支持 · `shared_interest` 共同兴趣 · `gift` 赠予分享 · `promise_kept` 守信 · `deep_talk` 深入交流 · `banter` 有趣互动 · `reconcile` 和解 · `loyalty` 维护站台 |
| 负向 | `disrespect` 冒犯贬低 · `promise_broken` 失信 · `harassment` 骚扰越界 · `betrayal` 背叛伤害 · `spam` 刷屏滥用 · `deception` 欺骗隐瞒 · `neglect` 冷落无视 · `boundary_push` 试探边界 |

单次事件权重 = 类型基准权重 × 严重度系数（轻微 0.6 / 明显 1.0 / 严重 1.8），
同一阶段内同类型事件重复出现时按 `1/(1+0.5n)` 边际递减。

### 阶段与跃迁条件

| 阶段 | 展示分区间 | 升级所需净正向证据 | 降级所需净负向证据 | 最短停留 | 无互动回落 |
|---|---|---|---|---|---|
| 排斥 | ≤ -60 | 6.0 | — | 12h | — |
| 保留 | -60 ~ -20 | 4.0 | 3.0 | 8h | 30 天 |
| 中立 | -20 ~ 20 | 4.0 | 3.0 | 4h | 60 天 |
| 亲近 | 20 ~ 60 | 8.0 | 4.0 | 8h | 90 天 |
| 偏爱 | 60 ~ 85 | 12.0 | 6.0 | 12h | 120 天 |
| 特别亲密 | ≥ 85 | — | 8.0 | 24h | 180 天 |

跃迁需要**同时**满足：净证据权重达阈值 **+** 出现至少 `FAVOR_STAGE_MIN_KINDS` 种不同类型的事件
**+** 已在当前阶段停留超过最短时间（滞后防抖）。跃迁成功后阶段内证据清零，富余部分结转。

### 时间的作用

- **证据衰减**：阶段内证据按 `FAVOR_EVIDENCE_HALF_LIFE_HOURS`（默认 72h）半衰期衰减，衰减的是证据权重而非分数。
- **无互动回落**：超过阶段对应的 `idle_demote_hours` 没有有效互动时，关系自然回落一级，并写入 `idle_demote` 事件。

### 记忆门槛（min_favor）

每条记忆可以带 `min_favor`：`0=公开 / 20=亲近 / 60=偏爱`。门槛现在按**阶段**判定：
`min_favor < 20` 对所有阶段开放，`20~59` 需要「亲近」及以上，`≥60` 需要「偏爱」及以上。
关系没到门槛时，这条记忆**不会**进正文，只会以标题形式出现在「#暂时不想细说的事」里。
关闭 `ENABLE_FAVOR_GATING` 即恢复为无条件注入。

### 防刷分

最小事件间隔、每日事件总数/正向数/负向数上限、同类型边际递减、升级需要多种类事件，
以及「证据必须是具体行为」——只有氛围词（聊得不错/感觉很好…）时不予记录。被拦下时会返回明确原因。

### LLM 工具

| 工具 | 类型 | 作用 |
|---|---|---|
| `记录关系事件` | BEHAVIOR | 记录一次关系事件，由状态机决定是否跃迁（改变关系的唯一正规入口） |
| `重设关系阶段` | BEHAVIOR | 人工直接设定阶段（覆盖状态机，清空阶段内证据） |
| `删除关系档案` | BEHAVIOR | 删除某用户档案与事件历史 |
| `查看关系档案` | AGENT | 查看某用户的阶段、阶段内证据与最近事件 |
| `列出关系档案` | AGENT | 列出本频道档案摘要 |
| `结算关系衰减` | AGENT | 手动跑一次证据衰减与回落结算 |
| `记住事实` / `查看事实` / `删除事实` | BEHAVIOR/AGENT | 结构化事实的增删查 |

`angel_remember` 支持 `min_favor` 参数；`angel_recall` 会自动按当前发言人的关系阶段门控结果。

### 群聊命令

> ⚠️ **带前缀的命令必须写前缀（默认 `/`）**。适配器配置项 `COMMAND_PREFIX` 决定前缀字符，本部署为 `/`。
> 这个闸门在 `BaseAdapter.detect_command()` 里，早于插件逻辑：`text.startswith(prefix)` 不成立就直接返回 `None`，
> 消息会被当成普通聊天记录存下来、既不触发命令也不触发 AI 回复，看起来就是「毫无反应」。
> 另有两点上游行为要知道：命令名写错（not found）时框架**既不回复也不记日志**，同样表现为毫无反应；
> 而且**命令系统先于频道 `is_active` 检查**，所以频道关着的时候命令仍然可用。
>
> ✅ 为了照顾群友记不住前缀，`查看好感度` / `好感榜` 这两个词额外支持**无前缀直接发**：
> 插件在消息钩子里做**精确等值匹配**（不做包含匹配，避免误触发），命中后自己把卡片发出去，
> 并返回 `BLOCK_TRIGGER` 阻止这条消息再唤醒 AI。带前缀的 `/查看好感度` 会被命令系统提前消费，
> 不会重复触发。开关是 `FAVOR_RANK_KEYWORD_ENABLED`，词表是 `FAVOR_RANK_KEYWORDS`。
>
> ℹ️ 两条入口的**发送通道不同**，所以形态本来就不一样：命令入口的文本会带 `≡NA≡:` 前缀且图文合并为一条，
> 关键词入口则是插件直发的独立图片消息。为了不让同一个功能看起来像两个东西，关键词入口**只发卡片图片**、
> 不再附带那行文字说明。详见 [为什么关键词入口只发图片、不发那行文字](#为什么关键词入口只发图片不发那行文字)。

| 命令 | 别名 | 权限 | 说明 |
|---|---|---|---|
| `/查看好感度`（也可不带 `/` 直接发 `查看好感度` / `好感榜`） | 好感榜 / fav_rank / favor_rank | 用户 | 本频道关系阶段排行榜（图片，失败回退文本） |
| `/好感度档案` | 关系档案 / fav_status / 档案 | 用户 | 查看自己（或指定用户）的档案 |
| `/好感度事件` | 关系事件 / fav_event | 超管 | `/好感度事件 <用户ID> <事件类型> <具体证据> [严重度1-3]` |
| `/好感度设定` | 关系设定 / fav_set | 超管 | `/好感度设定 <用户ID> <阶段>` |
| `/好感度删除` | 关系删除 / fav_remove | 超管 | `/好感度删除 <用户ID>` |

> 除排行榜外，其余命令**只认带前缀的形式**（无前缀钩子只做排行榜这一件事）。
>
> 英文别名统一用 `fav_*` 短横线风格（`fav_rank` / `fav_status` / `fav_event` / `fav_set` / `fav_remove`）。
> 之所以不用 `favor_set` / `favor_status` / `favor_remove` / `fvs`：这类短名很容易被其它插件占用，
> 而框架**不会清理已停用或已删除插件的命令注册**，撞名时用户敲命令只会收到「命令存在冲突」。
> 同理，`好感度排行` 这个别名与第三方插件的 `affinity_board` 撞名，故用 `好感榜` 代替。
> 插件已被卸载的旧命令名（如 `favor_status`）如确有需要，可在 `main.py` 里按需加回 `aliases`。
>
> 还要注意：**`/好感度`（不带「查看」）不是本插件的命令**，它命中第三方「抽老婆」插件的 `affinity`
> 别名（本月 CP 好感度），和本插件的关系阶段排行榜是两回事。本插件请用 `/查看好感度` 或 `/好感榜`。
> 同理 `FAVOR_RANK_KEYWORDS` 里**不要**填「好感度」，否则含义会和抽老婆的 CP 好感度混淆。

> **榜单里都有谁？**
> 默认 `FAVOR_AUTO_ENROLL=true`（聊过就进榜）：在本频道**发过言**的人都会被自动建档，
> 落在「中立」、零证据，所以榜单是一份**花名册**，新人也看得到自己。
> 随着关系事件累积，有人会往上升阶段，排序自然把他们排到前面（排序键：阶段 → 展示分 → 更新时间）。
>
> 关掉 `FAVOR_AUTO_ENROLL` 就回到纯事件制：档案只在**记录过关系事件**时才建立
> （`touch_favor` 只更新已存在的档案，不会凭空建档），事件来源是 AI 调用沙箱方法
> `记录关系事件`，或超管用 `/好感度事件` 手动记录。这时全新频道的榜单会提示「还没有建立任何关系档案」。
>
> ⚠️ 这两个开关有联动：**`FAVOR_AUTO_ENROLL` 开着但 `FAVOR_RANK_HIDE_EMPTY` 也开着**，
> 自动建档的空档案会被全部隐藏，榜单看起来还是空的。`FAVOR_RANK_HIDE_EMPTY` 默认已改为 `false`。

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