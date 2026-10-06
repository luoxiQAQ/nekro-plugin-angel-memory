from pydantic import Field

from nekro_agent.api.plugin import ConfigBase, ExtraField, NekroPlugin


plugin = NekroPlugin(
    name="天使记忆",
    module_name="nekro_memory_angel",
    description="分层长期记忆、滑动窗口短期记忆、结构化事实、回忆、用户画像、灵魂状态与事件驱动关系状态机",
    version="1.4.0",
    author="luoxiQAQ",
    url="https://github.com/luoxiQAQ/nekro-plugin-angel-memory",
    allow_sleep=False,
)


@plugin.mount_config()
class AngelMemoryConfig(ConfigBase):
    # ------------------------------------------------------------ 记忆总控

    ENABLE_AUTO_RECALL: bool = Field(default=True, title="启用自动回忆")
    AUTO_RECALL_LIMIT: int = Field(default=6, ge=1, le=20, title="自动回忆结果上限")
    PROMPT_MAX_CHARS: int = Field(
        default=6000,
        ge=1000,
        le=20000,
        title="提示词总字符预算",
        description="所有记忆分层的字符总和上限，按下面的预算比例切分；不会把全部记忆一股脑塞进去。",
    )
    ENABLE_AUTO_CONSOLIDATION: bool = Field(default=True, title="启用自动记忆整合")
    CONSOLIDATE_EVERY_USER_MESSAGES: int = Field(default=8, ge=2, le=100, title="每次整合间隔消息数")
    CONSOLIDATION_DELAY_SECONDS: int = Field(default=20, ge=1, le=300, title="整合延迟秒数")
    CONSOLIDATION_HISTORY_LIMIT: int = Field(default=30, ge=6, le=100, title="整合历史消息上限")
    CONSOLIDATION_MODEL_GROUP: str = Field(
        default="",
        title="整合模型组",
        description="留空则使用当前频道的聊天模型组。",
        json_schema_extra=ExtraField(ref_model_groups=True, model_type="chat").model_dump(),
    )
    ENABLE_HEURISTIC_REMEMBER: bool = Field(default=True, title="记住用户明确要求记住的内容")
    DEFAULT_MEMORY_IMPORTANCE: float = Field(default=0.65, ge=0.0, le=1.0, title="默认记忆重要度")
    MAX_MEMORIES_PER_SCOPE: int = Field(default=1000, ge=50, le=10000, title="每个作用域最大活跃记忆数")
    MAINTENANCE_INTERVAL_HOURS: int = Field(default=24, ge=1, le=720, title="维护间隔小时数")
    ARCHIVE_AFTER_DAYS: int = Field(default=180, ge=7, le=3650, title="弱记忆归档天数")
    ARCHIVE_STRENGTH_THRESHOLD: float = Field(default=0.28, ge=0.0, le=1.0, title="归档强度阈值")
    ENABLE_USER_PROFILE: bool = Field(default=True, title="启用用户画像")
    ENABLE_SOUL_STATE: bool = Field(default=True, title="启用灵魂状态")
    CLEAR_MEMORY_ON_CHANNEL_RESET: bool = Field(
        default=False,
        title="重置频道时清除记忆",
        description="开启后，在面板重置频道会同时清除该频道的全部记忆、笔记、画像、事实、摘要与关系档案；长期记忆默认跨频道重置保留。",
    )

    # ---------------------------------------------------------- 记忆分层

    ENABLE_SLIDING_WINDOW: bool = Field(
        default=True,
        title="启用短期滑动窗口",
        description="把最近若干条原始对话作为短期层注入；不落库、每轮重建，窗口之外的内容交给长期层沉淀。",
    )
    SLIDING_WINDOW_MESSAGES: int = Field(default=16, ge=2, le=100, title="滑动窗口消息条数")
    SLIDING_WINDOW_MSG_CHARS: int = Field(default=160, ge=20, le=1000, title="窗口内单条消息截断字符数")

    ENABLE_FACTS: bool = Field(
        default=True,
        title="启用结构化事实",
        description="把「谁·什么属性·什么值」抽成结构化记录持久化，检索时按需取用，而不是把原始对话反复塞进提示词。",
    )
    FACT_PROMPT_LIMIT: int = Field(default=8, ge=1, le=50, title="提示词中注入的事实条数")
    FACT_MAX_PER_CONSOLIDATION: int = Field(default=6, ge=1, le=30, title="每次整合最多抽取事实数")

    ENABLE_DIGEST: bool = Field(
        default=True,
        title="启用滚动摘要",
        description="每次整合把滑过窗口的对话压成一条摘要，形成中期记忆层。",
    )
    DIGEST_PROMPT_LIMIT: int = Field(default=2, ge=1, le=10, title="提示词中注入的摘要条数")
    DIGEST_MAX_CHARS: int = Field(default=400, ge=80, le=2000, title="单条摘要注入字符上限")

    PROMPT_BUDGET_WINDOW: int = Field(default=25, ge=0, le=80, title="预算占比：短期窗口")
    PROMPT_BUDGET_FACTS: int = Field(default=15, ge=0, le=80, title="预算占比：结构化事实")
    PROMPT_BUDGET_MEMORIES: int = Field(default=30, ge=0, le=80, title="预算占比：长期记忆")
    PROMPT_BUDGET_DIGEST: int = Field(default=10, ge=0, le=80, title="预算占比：滚动摘要")
    PROMPT_BUDGET_RELATION: int = Field(default=12, ge=0, le=80, title="预算占比：关系状态")
    PROMPT_BUDGET_SOUL: int = Field(default=8, ge=0, le=80, title="预算占比：灵魂状态")
    RESPECT_UPSTREAM_MEMORY: bool = Field(
        default=True,
        title="谦让上游记忆系统",
        description="检测到 NekroAgent 自带记忆系统开启时，自动压缩本插件的注入预算，避免两套记忆互相挤占上下文。",
    )

    # ---------------------------------------------------- 好感度（状态机）

    ENABLE_FAVORABILITY: bool = Field(
        default=True,
        title="启用关系状态机",
        description="按「频道 + 用户」维护关系阶段；变化由关系事件驱动，而不是纯数值加减。",
    )
    ENABLE_FAVOR_GATING: bool = Field(
        default=True,
        title="启用关系门槛门控记忆",
        description="开启后，记忆条目上的 min_favor 门槛生效：关系没到，该条记忆不会进正文，只进「暂时不想细说的事」。",
    )
    FAVOR_DEFAULT_STAGE: str = Field(
        default="中立",
        title="新档案默认关系阶段",
        description="可选：排斥 / 保留 / 中立 / 亲近 / 偏爱 / 特别亲密。",
    )
    FAVOR_AUTO_ENROLL: bool = Field(
        default=True,
        title="聊过就进榜（首次发言自动建档）",
        description=(
            "开启后，用户在本频道第一次发言就会建一条「中立、零证据」的关系档案，"
            "排行榜立刻有花名册，不必等关系事件。"
            "阶段跃迁仍然只由关系事件驱动，所以这不改变状态机语义。"
            "关闭后回到事件制：只有被记录过关系事件的人才会有档案。"
        ),
    )
    FAVOR_MAX_ABS_SCORE: int = Field(
        default=100, ge=10, le=10000, title="展示分绝对值上限",
        description="展示分只是从关系阶段投影出来的排序值，不是权威状态。",
    )
    FAVOR_EXPOSE_NUMBERS: bool = Field(
        default=False,
        title="提示词中暴露内部数值",
        description="默认关闭：只告诉模型当前阶段与互动指导语，不把分数/权重塞进提示词。",
    )
    FAVOR_MIN_INTERVAL_MINUTES: int = Field(
        default=3, ge=0, le=10080, title="同一用户两次关系事件的最小间隔（分钟）", description="0 表示不限制。",
    )
    FAVOR_MAX_EVENTS_PER_DAY: int = Field(default=30, ge=1, le=500, title="同一用户每日最多关系事件数")
    FAVOR_MAX_POSITIVE_PER_DAY: int = Field(default=20, ge=1, le=500, title="同一用户每日最多正向事件数")
    FAVOR_MAX_NEGATIVE_PER_DAY: int = Field(default=12, ge=1, le=500, title="同一用户每日最多负向事件数")
    FAVOR_REPEAT_DECAY: float = Field(
        default=0.25, ge=0.0, le=5.0, title="同类型事件边际递减系数",
        description="同一阶段内同类型事件重复出现时权重按 1/(1+k·n) 衰减。",
    )
    FAVOR_STAGE_MIN_KINDS: int = Field(
        default=1, ge=1, le=8, title="升级所需的最少事件种类数",
        description="防止单一种类事件反复刷分推动阶段跃迁。默认 1 = 不强制种类多样性。",
    )
    FAVOR_EVIDENCE_HALF_LIFE_HOURS: int = Field(
        default=72, ge=1, le=8760, title="阶段内证据半衰期（小时）",
        description="证据随时间按半衰期衰减；衰减的是证据权重，不是分数。",
    )
    FAVOR_ERODE_INTERVAL_HOURS: int = Field(default=12, ge=1, le=8760, title="证据衰减结算间隔（小时）")
    FAVOR_REQUIRE_CONCRETE_EVIDENCE: bool = Field(
        default=False, title="要求具体证据",
        description="开启后，证据只有「聊得不错」这类氛围描述、没有具体行为时不予记录。默认关闭。",
    )
    FAVOR_AI_PROMOTE_ENABLED: bool = Field(
        default=True,
        title="允许 AI 自主提升关系阶段",
        description=(
            "开启后，AI 可以在对话中判断「这个人值得更进一步」并直接把关系阶段提升一级，"
            "不再需要攒够事件种类与停留时长。"
            "这是把「要不要提升」的判断权交给 AI 的开关；关闭后 AI 只能通过记录关系事件间接影响阶段。"
        ),
    )
    FAVOR_AI_PROMOTE_PER_DAY: int = Field(
        default=3, ge=1, le=50, title="同一用户每日可被 AI 自主提升的次数上限",
        description="防止通过话术诱导 AI 反复给自己刷阶段；超限后本次提升被拒绝。",
    )
    FAVOR_MAX_EVIDENCE_CHARS: int = Field(default=200, ge=20, le=2000, title="单条事件证据字符上限")
    FAVOR_MAX_EVENT_HISTORY: int = Field(default=12, ge=1, le=200, title="单用户事件记录保留条数")
    FAVOR_PROMPT_EVENT_LIMIT: int = Field(default=3, ge=1, le=10, title="提示词中展示的最近事件条数")
    FAVOR_GROUP_OVERVIEW_LIMIT: int = Field(default=3, ge=1, le=10, title="无明确触发用户时的关系摘要数")
    FAVOR_MAX_TAGS: int = Field(default=6, ge=1, le=32, title="单用户关系标签上限")

    # ------------------------------------------------------- 排行榜卡片

    FAVOR_RANK_CARD_ENABLED: bool = Field(
        default=True, title="排行榜出图", description="关闭后「查看好感度」只回纯文本；缺少 Pillow 或中文字体时也会自动回退纯文本。",
    )
    FAVOR_RANK_LIMIT: int = Field(default=20, ge=1, le=40, title="排行榜最多展示人数")
    FAVOR_RANK_HIDE_EMPTY: bool = Field(
        default=False,
        title="排行榜隐藏空档案",
        description=(
            "隐藏既没有事件、也没有任何变动记录的空档案。"
            "默认关闭：配合「聊过就进榜」时，刚建档的人本来就该出现在榜单上。"
            "若开启 FAVOR_AUTO_ENROLL 又打开本项，自动建档的人会被全部隐藏，榜单会看起来还是空的。"
        ),
    )
    FAVOR_RANK_CARD_FONT: str = Field(
        default="", title="排行榜卡片中文字体路径", description="留空则自动探测系统字体（Noto Sans CJK / 微软雅黑 / 苹方）。",
    )
    FAVOR_RANK_AVATAR: bool = Field(
        default=True, title="排行榜拉取头像", description="按 QQ 号从 qlogo 拉头像；关闭后卡片用昵称首字占位。",
    )
    FAVOR_RANK_KEYWORD_ENABLED: bool = Field(
        default=True,
        title="允许无前缀关键词触发排行榜",
        description=(
            "开启后，群里直接发「查看好感度」（不带框架命令前缀 /）也会出排行榜。"
            "Nekro 的命令系统强制要求前缀，不带前缀的文本不会进入命令系统，"
            "这里用消息钩子精确匹配关键词来兜底，命中后阻止该消息再唤醒 AI。"
        ),
        json_schema_extra=ExtraField(is_hidden=True).model_dump(),
    )
    FAVOR_RANK_KEYWORDS: str = Field(
        default="查看好感度,好感榜",
        title="无前缀触发关键词",
        description=(
            "逗号或空格分隔，必须与整条消息完全相等才触发（不做包含匹配，避免误触发）。"
            "注意不要填「好感度」——它是第三方「抽老婆」插件 affinity 的别名，含义不同。"
        ),
        json_schema_extra=ExtraField(is_hidden=True).model_dump(),
    )
    FAVOR_RANK_AI_TRIGGER_ENABLED: bool = Field(
        default=True,
        title="允许 AI 按自然语言查看排行榜",
        description=(
            "开启后，插件会把「查看好感度排行榜」这个工具交给 AI，"
            "群友用自然语言（「看看好感度排行」「好感榜怎么样」）也能拿到排行榜卡片。"
            "命中与否由 AI 判断，所以更灵活，代价是这类消息会正常走一次模型。"
            "关闭后该工具对 AI 不可见，只剩 /查看好感度 命令与无前缀关键词两条精确入口。"
        ),
        json_schema_extra=ExtraField(is_hidden=True).model_dump(),
    )
    WEBUI_ACCESS_KEY: str = Field(
        default="",
        title="WebUI 访问密钥",
        description="留空表示只能用 NekroAgent 管理员身份访问好感度管理页；填写后可用 ?key=xxx 免登录访问。",
    )


config: AngelMemoryConfig = plugin.get_config(AngelMemoryConfig)
