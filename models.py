from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
