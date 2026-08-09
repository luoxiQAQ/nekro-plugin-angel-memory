from pydantic import Field

from nekro_agent.api.plugin import ConfigBase, ExtraField, NekroPlugin


plugin = NekroPlugin(
    name="天使记忆",
    module_name="nekro_memory_angel",
    description="原生长期记忆、回忆、用户画像、灵魂状态与记忆整合插件",
    version="1.0.4",
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


config: AngelMemoryConfig = plugin.get_config(AngelMemoryConfig)
