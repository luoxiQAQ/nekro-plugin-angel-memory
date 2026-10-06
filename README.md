# 天使记忆 (Angel Memory) — NekroAgent 插件

[`astrbot_plugin_angel_memory`](https://github.com/kawayiYokami/astrbot_plugin_angel_memory) 的原生 NekroAgent 移植版本。
无需 AstrBot 或 Angel Heart。本移植使用 NekroAgent 的生命周期钩子、提示词注入、沙盒方法、模型组、频道历史和认证插件路由。

在原插件的基础上新增了**好感度系统**：事件驱动的分阶段关系状态机、聊过就进榜、排行榜卡片，
以及一个内嵌在面板插件详情页「页面」Tab 里的**管理控制台**（概览 / 好感度档案 / 关系事件 /
记忆与笔记 / 规则与门控 / 数据维护）。
记忆侧保持分层注入（短期滑动窗口 → 滚动摘要 → 结构化事实 → 长期记忆 → 用户画像 / 灵魂状态），
各层按权重分配字符预算，不会一股脑全塞进提示词。

## 安装

把完整的 `nekro_memory_angel` 目录放进 NekroAgent 的插件目录：

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

重启 NekroAgent，在插件管理页启用并配置「天使记忆」。**无需额外安装任何依赖。**

> **版本要求**
>
> - **NekroAgent ≥ 2.4.0**：完整功能，含面板插件详情页的「页面」Tab 管理控制台。
> - **NekroAgent < 2.4.0**：可正常加载与使用记忆 / 好感度功能，但**没有**「页面」Tab
>   管理控制台（该 Tab 依赖框架 2.4.0 引入的 `webui_path`）。
>   v1.5.2 起插件会自动探测框架能力并优雅降级；v1.5.0 / v1.5.1 在旧版框架上会因
>   `unexpected keyword argument 'webui_path'` 直接加载失败，请升级插件或框架。
>
> **中文字体（排行榜卡片）**
>
> 排行榜卡片需要中文字体渲染。**v1.5.3 起插件已自带一份子集字体**
> （`assets/fonts/`，约 6 MB），因此在**未安装中文字体的环境**（例如官方
> `nekro-agent` 镜像只带 DejaVu）也能正常出图。
> 若你的镜像已装 `fonts-noto-cjk` 等系统字体，可通过 `FAVOR_RANK_CARD_FONT`
> 指定优先使用自己的字体。

## 功能

**记忆（移植自原插件）**

- `angel_remember` / `angel_recall` / `angel_note_read` / `angel_note_create`：记忆与笔记的写入、检索、读取。
- 分层记忆与分层预算注入：短期滑动窗口、滚动摘要、结构化事实（`记住事实` / `查看事实` / `删除事实`）、长期记忆、用户画像与灵魂状态。
- 可选的 LLM 记忆整合（一次调用同时抽取记忆、事实与滚动摘要）、自动提示词回忆、维护与归档。
- JSON 导入 / 导出、AstrBot 数据迁移工具。
- SQLite FTS5 检索，支持中文与二元组归一化。

**好感度（新增）**

- 关系状态机：按「频道 + 用户」维护关系**阶段**（排斥 / 保留 / 中立 / 亲近 / 偏爱 / 特别亲密），
  由**关系事件**驱动跃迁，而不是纯数值加减；证据按半衰期衰减，长期无互动自动回落一级。
- 聊过就进榜（`FAVOR_AUTO_ENROLL`，默认开）：在本频道发过言的人自动建档，落在「中立」零证据，
  榜单立刻是一份花名册；阶段跃迁仍然只由关系事件驱动。
- 关系门槛门控：记忆可带 `min_favor`，关系没到就不会被讲出来。
- 排行榜卡片：1280 宽双列布局，金 / 银 / 铜名次徽章、圆形头像、进度条与阶段标签，
  配色遵循中文习惯的「涨红跌绿」。
- 三条入口：`/查看好感度` 命令、群里不带 `/` 直接发 `查看好感度` / `好感榜`、以及自然语言（由 AI 判断意图）。
- **AI 自主提升（`FAVOR_AI_PROMOTE_ENABLED`，默认开）**：把「要不要更进一步」的判断权交给 AI——
  AI 可以在对话里用「提升关系阶段」工具直接把某人提升一级，不必先攒够事件种类与停留时长。
  保留每日次数上限（`FAVOR_AI_PROMOTE_PER_DAY`，默认 3）防止话术诱导刷阶段。
- 防刷分（2026-10 已放宽）：最小事件间隔、每日事件上限、同类型边际递减。
  **放宽的是「更容易变好」**：升级阈值下调、每日上限调大、不再强制多类型事件与具体证据措辞；
  **降级侧阈值一律未动**，关系不会因为一时情绪就掉级。
- **管理控制台**：面板插件详情页的「页面」Tab 内嵌仪表盘，可浏览档案与事件流水、
  人工设定阶段 / 补录事件、查看生效中的规则与门控参数、结算衰减与导出数据。见下方「管理控制台」。

## 群聊命令

| 命令 | 别名 | 权限 | 说明 |
|---|---|---|---|
| `/查看好感度`（也可不带 `/` 直接发 `查看好感度` / `好感榜`） | 好感榜 / fav_rank / favor_rank | 用户 | 本频道关系阶段排行榜（图片，失败回退文本） |
| `/好感度档案` | 关系档案 / fav_status / 档案 | 用户 | 查看自己（或指定用户）的档案 |
| `/好感度事件` | 关系事件 / fav_event | 超管 | `/好感度事件 <用户ID> <事件类型> <具体证据> [严重度1-3]` |
| `/好感度设定` | 关系设定 / fav_set | 超管 | `/好感度设定 <用户ID> <阶段>` |
| `/好感度删除` | 关系删除 / fav_remove | 超管 | `/好感度删除 <用户ID>` |

带前缀的命令必须写前缀（默认 `/`，由适配器 `COMMAND_PREFIX` 决定），只有排行榜额外支持无前缀直发与自然语言。
排行榜卡片依赖 Pillow 与中文字体；Pillow 由 NekroAgent 自带，中文字体已随插件打包，两者都不可用时自动回退纯文本。

## 主要配置

- `ENABLE_AUTO_RECALL`：将相关历史证据注入提示词。
- `AUTO_RECALL_LIMIT`：灵魂状态缩放前的最大自动记忆命中数。
- `PROMPT_MAX_CHARS`：所有记忆分层的字符总预算（按各层权重切分）。
- `ENABLE_SLIDING_WINDOW` / `SLIDING_WINDOW_MESSAGES` / `SLIDING_WINDOW_MSG_CHARS`：短期滑动窗口。
- `ENABLE_FACTS` / `FACT_PROMPT_LIMIT` / `FACT_MAX_PER_CONSOLIDATION`：结构化事实层。
- `ENABLE_DIGEST` / `DIGEST_PROMPT_LIMIT` / `DIGEST_MAX_CHARS`：滚动摘要层。
- `PROMPT_BUDGET_WINDOW` / `_FACTS` / `_MEMORIES` / `_DIGEST` / `_RELATION` / `_SOUL`：各层预算权重。
- `RESPECT_UPSTREAM_MEMORY`：检测到上游记忆系统在跑时，自动把本插件预算压缩到 60%。
- `ENABLE_AUTO_CONSOLIDATION` / `CONSOLIDATE_EVERY_USER_MESSAGES` / `CONSOLIDATION_MODEL_GROUP`：LLM 记忆整合。
- `ENABLE_HEURISTIC_REMEMBER`：记住中文「记住这个」等明确要求。
- `ENABLE_USER_PROFILE` / `ENABLE_SOUL_STATE`：用户画像与灵魂状态。
- `ENABLE_FAVORABILITY`：启用关系状态机。
- `ENABLE_FAVOR_GATING` / `FAVOR_DEFAULT_STAGE` / `FAVOR_AUTO_ENROLL`：关系门槛门控、新档案默认阶段、「聊过就进榜」。
- `FAVOR_EXPOSE_NUMBERS`：是否把内部证据权重 / 展示分写进提示词（默认关闭）。
- `FAVOR_MIN_INTERVAL_MINUTES` / `FAVOR_MAX_EVENTS_PER_DAY` / `FAVOR_MAX_POSITIVE_PER_DAY` / `FAVOR_MAX_NEGATIVE_PER_DAY`：事件频率与每日上限（默认 3 分钟 / 30 / 20 / 12）。
- `FAVOR_REPEAT_DECAY` / `FAVOR_STAGE_MIN_KINDS`：同类型事件边际递减（默认 0.25）、升级所需事件种类数（默认 1 = 不强制）。
- `FAVOR_EVIDENCE_HALF_LIFE_HOURS` / `FAVOR_ERODE_INTERVAL_HOURS`：证据半衰期与衰减结算间隔。
- `FAVOR_REQUIRE_CONCRETE_EVIDENCE`：证据必须是具体行为（只有氛围词时不予记录）。**默认关闭**。
- `FAVOR_AI_PROMOTE_ENABLED` / `FAVOR_AI_PROMOTE_PER_DAY`：AI 自主提升关系阶段的总开关（默认开）与每人每日次数上限（默认 3）。
- `FAVOR_MAX_ABS_SCORE`：展示分绝对值上限（仅用于排序展示，不是权威状态）。
- `FAVOR_MAX_EVENT_HISTORY` / `FAVOR_PROMPT_EVENT_LIMIT` / `FAVOR_GROUP_OVERVIEW_LIMIT` / `FAVOR_MAX_TAGS`：事件流水保留条数、提示词中展示的最近事件数、关系摘要数、关系标签上限。
- `FAVOR_RANK_CARD_ENABLED` / `FAVOR_RANK_LIMIT` / `FAVOR_RANK_HIDE_EMPTY` / `FAVOR_RANK_CARD_FONT` / `FAVOR_RANK_AVATAR`：排行榜卡片。
- `FAVOR_RANK_KEYWORD_ENABLED` / `FAVOR_RANK_KEYWORDS`：无前缀关键词触发排行榜（默认开，词表 `查看好感度,好感榜`）。
- `FAVOR_RANK_AI_TRIGGER_ENABLED`：把「查看好感度排行榜」工具交给 AI，让自然语言也能查榜单（默认开）。
- `WEBUI_ACCESS_KEY`：好感度管理页的免登录访问密钥（留空则只能用 NekroAgent 管理员身份访问）。自己定一串字符即可，**没有「申请 / 生成」这一步**。
- `CLEAR_MEMORY_ON_CHANNEL_RESET`：开启后，在面板重置频道会同时清除该频道的全部记忆与关系档案（默认关闭）。

## 管理控制台

插件自带一个管理控制台，两个入口：

1. **面板内嵌（推荐）** —— 在 NekroAgent 面板的插件详情页点「**页面**」Tab，控制台直接嵌在里面。
   因为是同源 iframe，它会自动读取面板登录态，**不需要任何密钥**；记忆、笔记、数据导出
   这些需要管理员权限的功能也都能用。
2. **独立页面** —— 浏览器打开：

```text
http://<面板地址>:8021/plugins/luoxiQAQ.nekro_memory_angel/ui
```

独立打开时，鉴权满足任意一条即可：

1. **先在 NekroAgent 面板登录**，再打开本页 —— 页面会自己读取面板的登录态（`localStorage` 里的
   `auth-storage`），什么都不用填。最省事、也最安全。
2. **在页面输入框里填 `WEBUI_ACCESS_KEY`** —— 页面会认出这是密钥而不是 chat_key，把它记在本机
   浏览器里，并列出所有有数据的频道供点选。
3. **把密钥拼进网址**：`.../ui?key=<那串>`。页面读到后会立刻把它从地址栏抹掉，
   避免留在浏览器历史和分享链接里。

> ⚠️ 用访问密钥只能访问好感度相关接口。「记忆与笔记」「数据维护」里的管理员接口会返回 401，
> 页面会提示改用面板内的「页面」Tab。
>
> ⚠️ 面板端口若对公网开放，带 `?key=` 的网址一旦泄露就等于一个长期有效的免登录入口。
> 优先用面板内的「页面」Tab。

### 页面结构

左侧边栏六个页面：

| 页面 | 内容 |
|---|---|
| **概览** | 关系档案数 / 事件总数 / 正面与负面关系 / 平均展示分 / 数据频道；关系衰减参数；门控与安全开关；关系阶段分布；记忆分层体量 |
| **好感度档案** | 关系档案总表（阶段、展示分、阶段内证据、标签、最近理由、最近互动），支持按昵称 / ID / 标签筛选与多种排序。点任意一行打开右侧详情抽屉：升级进度、证据构成、正向与负向事件种类、事件流水，并可设定阶段 / 记录事件 / 删除 |
| **关系事件** | 按用户查看事件流水时间线（类型、权重、证据、阶段跃迁）；也可人工补录一次关系事件 |
| **记忆与笔记** | 长期记忆 / 结构化事实 / 笔记三个子页；带 `min_favor` 门槛的记忆会标出来 |
| **规则与门控** | 阶段阈值表（分数区间、升阶 / 降阶阈值、最短停留、闲置回落、互动指导语）、好感度增减参考（18 种事件类型的基准权重与判定说明）、事件准入约束、严重度系数。**只读**，改规则请到插件配置页 |
| **数据维护** | 立即结算证据衰减、记忆维护（归档 / 裁剪）、对齐同群实例档案、导出全部数据、生成排行榜卡片、清空当前频道（双重确认） |

页面每 15 秒自动刷新一次；页面不可见、或正在开弹窗 / 抽屉时会自动暂停，避免打断正在填的表单。

### 多个账号接同一个群时

同一个群被多个账号同时接收消息时，每个账号会各自持有一份关系档案 —— 它们是**互相独立**的。
如果只在面板里改了当前选中账号的阶段，另一个账号回话时仍按旧阶段说话（表现为「面板里设成排斥，
聊天里还是中立」）。

「设定关系阶段」弹窗为此做了三件事：

1. 列出**同群各实例当前阶段**，不一致时标红提醒；
2. 提供**应用范围**三选一：仅当前频道 / 同群的其它实例（默认）/ 该用户的所有频道；
3. 可顺带填**互动基调**（留空则按所选阶段自动生成；换阶段会自动清空旧基调）。

若历史上已经改歪了，到「数据维护」页点「**对齐同群实例档案**」：它会把各实例里
**还没被人工设定过、也没有任何关系事件**的空档案，对齐到该群里最有信息量的那份。
先给预览、确认后才落库；人工设过或有事件的档案一律不碰。

## 许可证

保留原始项目的 GNU GPL v3 许可与署名。完整许可证文本见 `LICENSE`，署名信息见 `NOTICE`。
