from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# ------------------------------------------------------------------ 记忆分层

# 记忆层级：L0 工作记忆（滑动窗口，不落库）/ L1 短期情景 / L2 结构化事实
# L3 长期语义 / L4 画像与灵魂状态
TIER_WORKING = "working"
TIER_EPISODIC = "episodic"
TIER_FACT = "fact"
TIER_SEMANTIC = "semantic"
TIER_PROFILE = "profile"

MEMORY_TYPE_TO_TIER: dict[str, str] = {
    "episodic": TIER_EPISODIC,
    "semantic": TIER_SEMANTIC,
    "preference": TIER_SEMANTIC,
    "relationship": TIER_SEMANTIC,
    "commitment": TIER_SEMANTIC,
    "experience": TIER_SEMANTIC,
}


def tier_of_memory_type(memory_type: str) -> str:
    return MEMORY_TYPE_TO_TIER.get(str(memory_type or "").strip().lower(), TIER_SEMANTIC)


@dataclass(slots=True)
class MemoryRecord:
    id: str
    short_id: int
    chat_key: str
    user_id: str
    memory_type: str
    content: str
    summary: str
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5
    confidence: float = 0.8
    access_count: int = 0
    status: str = 'active'
    source: str = 'manual'
    created_at: float = 0.0
    updated_at: float = 0.0
    last_accessed_at: float = 0.0
    # 关系门槛：只有发言人的关系阶段达到该门槛，这条记忆才会被注入（0=公开）
    min_favor: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def tier(self) -> str:
        return tier_of_memory_type(self.memory_type)


@dataclass(slots=True)
class NoteRecord:
    id: str
    short_id: int
    chat_key: str
    title: str
    content: str
    tags: list[str] = field(default_factory=list)
    source: str = 'agent'
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SoulState:
    chat_key: str
    recall_depth: float = 0.5
    impression_depth: float = 0.5
    expression_desire: float = 0.5
    creativity: float = 0.5
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# -------------------------------------------------------------- 结构化事实


@dataclass(slots=True)
class FactRecord:
    """L2 结构化事实：主体-属性-值，持久化且可精确检索，不必塞进提示词。"""

    id: str
    short_id: int
    chat_key: str
    user_id: str
    subject: str
    attribute: str
    value: str
    confidence: float = 0.8
    source: str = 'auto'
    status: str = 'active'
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        subject = self.subject or self.user_id or "?"
        return f"{subject} · {self.attribute}：{self.value}"


@dataclass(slots=True)
class DigestRecord:
    """L1 滚动摘要：滑动窗口滚过的一段对话的压缩结果。"""

    id: str
    chat_key: str
    window_start: int
    window_end: int
    summary: str
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------ 好感度（状态机）


@dataclass(slots=True)
class FavorProfile:
    """频道级、按用户维护的关系档案。

    权威状态是 `stage` + 阶段内证据累积（pos_weight/neg_weight + 事件种类集合）；
    `score` 只是投影出来的展示分，供排行榜与记忆门槛使用。
    """

    chat_key: str
    user_id: str
    display_name: str = ''
    stage: str = '中立'
    stage_entered_at: float = 0.0
    pos_weight: float = 0.0
    neg_weight: float = 0.0
    pos_kinds: list[str] = field(default_factory=list)
    neg_kinds: list[str] = field(default_factory=list)
    score: int = 0
    summary: str = ''
    interaction_hint: str = ''
    tags: list[str] = field(default_factory=list)
    last_reason: str = ''
    last_kind: str = ''
    last_adjust_at: float = 0.0
    last_event_at: float = 0.0
    event_count: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    last_interaction_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_empty(self) -> bool:
        """空档案：没有阶段证据、没有事件、也没有变动记录，排行榜里应隐藏。"""
        return (
            int(self.event_count) <= 0
            and not self.last_reason
            and float(self.pos_weight) == 0.0
            and float(self.neg_weight) == 0.0
            and self.stage == '中立'
        )


@dataclass(slots=True)
class FavorEvent:
    """一次关系事件：事件溯源里的那一条。"""

    id: int
    chat_key: str
    user_id: str
    kind: str
    label: str
    polarity: int
    severity: int
    weight: float
    evidence: str
    stage_before: str
    stage_after: str
    score_after: int
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
