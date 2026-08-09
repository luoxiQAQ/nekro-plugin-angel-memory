from pydantic import Field

from nekro_agent.api.plugin import ConfigBase, ExtraField, NekroPlugin


plugin = NekroPlugin(
    name="Angel Memory",
    module_name="nekro_plugin_angel_memory",
    description="Native long-term memory, recall, user profiles, soul state and consolidation for NekroAgent",
    version="1.0.0",
    author="kawayiYokami_NekroPort",
    url="https://github.com/kawayiYokami/astrbot_plugin_angel_memory",
    allow_sleep=True,
    sleep_brief="Provides long-term memory, recall, notes, profiles and background consolidation.",
)


@plugin.mount_config()
class AngelMemoryConfig(ConfigBase):
    ENABLE_AUTO_RECALL: bool = Field(default=True, title="Enable automatic recall")
    AUTO_RECALL_LIMIT: int = Field(default=6, ge=1, le=20, title="Automatic recall result limit")
    PROMPT_MAX_CHARS: int = Field(default=6000, ge=1000, le=20000, title="Memory prompt character limit")
    ENABLE_AUTO_CONSOLIDATION: bool = Field(default=True, title="Enable automatic consolidation")
    CONSOLIDATE_EVERY_USER_MESSAGES: int = Field(default=8, ge=2, le=100, title="Messages per consolidation")
    CONSOLIDATION_DELAY_SECONDS: int = Field(default=20, ge=1, le=300, title="Consolidation delay in seconds")
    CONSOLIDATION_HISTORY_LIMIT: int = Field(default=30, ge=6, le=100, title="Consolidation history message limit")
    CONSOLIDATION_MODEL_GROUP: str = Field(
        default="",
        title="Consolidation model group",
        description="Leave empty to use the active channel chat model group.",
        json_schema_extra=ExtraField(ref_model_groups=True, model_type="chat").model_dump(),
    )
    ENABLE_HEURISTIC_REMEMBER: bool = Field(default=True, title="Remember explicit user statements")
    DEFAULT_MEMORY_IMPORTANCE: float = Field(default=0.65, ge=0.0, le=1.0, title="Default memory importance")
    MAX_MEMORIES_PER_SCOPE: int = Field(default=1000, ge=50, le=10000, title="Maximum active memories per scope")
    MAINTENANCE_INTERVAL_HOURS: int = Field(default=24, ge=1, le=720, title="Maintenance interval in hours")
    ARCHIVE_AFTER_DAYS: int = Field(default=180, ge=7, le=3650, title="Archive weak memories after days")
    ARCHIVE_STRENGTH_THRESHOLD: float = Field(default=0.28, ge=0.0, le=1.0, title="Archive strength threshold")
    ENABLE_USER_PROFILE: bool = Field(default=True, title="Enable user profiles")
    ENABLE_SOUL_STATE: bool = Field(default=True, title="Enable soul state")


config: AngelMemoryConfig = plugin.get_config(AngelMemoryConfig)
