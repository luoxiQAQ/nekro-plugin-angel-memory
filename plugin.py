from pydantic import Field

from nekro_agent.api.plugin import ConfigBase, ExtraField, NekroPlugin


plugin = NekroPlugin(
    name="天使记忆",
    module_name="nekro_memory_angel",
    description="原生长期记忆、回忆、用户画像、灵魂状态、好感度关系与记忆整合插件",
    version="1.1.0",
    author="luoxiQAQ",
    url="https://github.com/luoxiQAQ/nekro-plugin-angel-memory",
    allow_sleep=False,
)


@plugin.mount_config()
class AngelMemoryConfig(ConfigBase):
    ENABLE_AUTO_RECALL: bool = Field(default=True, title="启用自动回忆")
    AUTO_RECALL_LIMIT: int = Field(default=6, ge=1, le=20, title="自动回忆结果上限")
    PROMPT_MAX_CHARS: int = Field(default=6000, ge=1000, le=20000, title="记忆提示词字符上限")
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
        description="开启后，在面板重置频道会同时清除该频道的全部记忆、笔记、画像与灵魂状态；长期记忆默认跨频道重置保留。",
    )

    # ------------------------------------------------------------- 好感度

    ENABLE_FAVORABILITY: bool = Field(
        default=True,
        title="启用好感度",
        description="开启后按「频道 + 用户」维护长期关系档案，并把当前发言人的关系卡注入提示词。",
    )
    ENABLE_FAVOR_GATING: bool = Field(
        default=True,
        title="启用好感度门槛门控记忆",
        description="开启后，记忆条目上的 min_favor 门槛生效：发言人好感度不够时，该条记忆不会被注入正文，只会进「暂时不想细说的事」。",
    )
    FAVOR_DEFAULT_SCORE: int = Field(default=0, ge=-100, le=100, title="新档案默认好感度")
    FAVOR_MAX_ABS_SCORE: int = Field(default=100, ge=10, le=10000, title="好感度绝对值上限")
    FAVOR_MAX_SINGLE_DELTA: int = Field(
        default=10, ge=1, le=100, title="单次调整绝对值上限", description="超出会被自动收敛到该值。",
    )
    FAVOR_MIN_INTERVAL_MINUTES: int = Field(
        default=30, ge=0, le=10080, title="同一用户两次调整的最小间隔（分钟）", description="0 表示不限制。",
    )
    FAVOR_MAX_DAILY_GAIN: int = Field(default=20, ge=1, le=1000, title="同一用户每日最多净加分")
    FAVOR_MAX_DAILY_LOSS: int = Field(default=30, ge=1, le=1000, title="同一用户每日最多净扣分")
    FAVOR_MARGINAL_DECAY: bool = Field(
        default=True, title="边际递减", description="分数越高，同样的行为加分越少（≥60 折半，≥85 折至 30%）。",
    )
    FAVOR_REQUIRE_CONCRETE_REASON: bool = Field(
        default=True, title="要求具体理由", description="理由只有「喜欢/开心/不错」这类氛围词、没有具体行为时不予加分。",
    )
    FAVOR_MAX_EVENT_HISTORY: int = Field(default=8, ge=1, le=100, title="单用户变动记录保留条数")
    FAVOR_PROMPT_EVENT_LIMIT: int = Field(default=3, ge=1, le=10, title="提示词中展示的变动条数")
    FAVOR_GROUP_OVERVIEW_LIMIT: int = Field(
        default=3, ge=1, le=10, title="无明确触发用户时的档案摘要数",
    )
    FAVOR_MAX_TAGS: int = Field(default=6, ge=1, le=32, title="单用户关系标签上限")
    FAVOR_DECAY_ENABLED: bool = Field(default=True, title="启用好感度衰减", description="长时间不互动自动降温。")
    FAVOR_DECAY_INTERVAL_HOURS: int = Field(default=24, ge=1, le=8760, title="衰减触发间隔（小时）")
    FAVOR_DECAY_PERCENT: int = Field(default=3, ge=1, le=100, title="每次衰减百分比（向上取整）")
    FAVOR_RECOVER_ENABLED: bool = Field(default=True, title="启用负分回升", description="负分随时间自动回升到 0。")
    FAVOR_RECOVER_INTERVAL_HOURS: int = Field(default=12, ge=1, le=8760, title="回升触发间隔（小时）")
    FAVOR_RECOVER_PERCENT: int = Field(default=5, ge=1, le=100, title="每次回升百分比（至少 +1）")

    # ------------------------------------------------------- 排行榜卡片

    FAVOR_RANK_CARD_ENABLED: bool = Field(
        default=True, title="排行榜出图", description="关闭后「查看好感度」只回纯文本；缺少 Pillow 或中文字体时也会自动回退纯文本。",
    )
    FAVOR_RANK_LIMIT: int = Field(default=20, ge=1, le=40, title="排行榜最多展示人数")
    FAVOR_RANK_HIDE_EMPTY: bool = Field(
        default=True, title="排行榜隐藏空档案", description="隐藏既没有分数、也没有任何变动记录的空档案。",
    )
    FAVOR_RANK_CARD_FONT: str = Field(
        default="", title="排行榜卡片中文字体路径", description="留空则自动探测系统字体（Noto Sans CJK / 微软雅黑 / 苹方）。",
    )
    FAVOR_RANK_AVATAR: bool = Field(
        default=True, title="排行榜拉取头像", description="按 QQ 号从 qlogo 拉头像；关闭后卡片用昵称首字占位。",
    )
    WEBUI_ACCESS_KEY: str = Field(
        default="",
        title="WebUI 访问密钥",
        description="留空表示只能用 NekroAgent 管理员身份访问好感度管理页；填写后可用 ?key=xxx 免登录访问。",
    )


config: AngelMemoryConfig = plugin.get_config(AngelMemoryConfig)
