from __future__ import annotations

import json
import math
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from .favorability import (
    DEFAULT_STAGE,
    EVENT_KINDS,
    STAGE_NAMES,
    EventLimits,
    EventOutcome,
    StageDecision,
    TransitionRules,
    clamp_stage,
    decide_stage,
    evaluate_event,
    evidence_decay,
    kind_label,
    project_score,
    score_to_stage,
    stage_index,
)
from .models import DigestRecord, FactRecord, FavorProfile, MemoryRecord, NoteRecord, SoulState

ASCII_PATTERN = re.compile(r'[a-zA-Z0-9_-]{2,}')
CJK_PATTERN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]+')

def clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def normalize_tags(tags: Iterable[str] | str | None) -> list[str]:
    if isinstance(tags, str):
        tags = re.split(r"[,;\uFF0C\uFF1B]", tags)
    values: list[str] = []
    for tag in tags or []:
        value = str(tag).strip().lower()
        if value and value not in values:
            values.append(value)
    return values[:32]


def search_tokens(text: str) -> list[str]:
    text = " ".join(str(text or "").lower().split())
    tokens = ASCII_PATTERN.findall(text)
    for fragment in CJK_PATTERN.findall(text):
        chars = list(fragment)
        tokens.extend(chars)
        tokens.extend("".join(chars[index : index + 2]) for index in range(len(chars) - 1))
    return list(dict.fromkeys(token for token in tokens if token))[:160]


def search_text(*parts: str) -> str:
    return " ".join(search_tokens("\n".join(parts)))


def match_query(query: str) -> str:
    tokens = [token.replace(chr(34), "") for token in search_tokens(query)[:32]]
    return " OR ".join(chr(34) + token + chr(34) for token in tokens)


def channel_base(chat_key: str) -> str:
    """从 chat_key 推导「频道本体」（把实例标识换成适配器前缀）。

    部分部署会把同一个群交给多个账号同时接收消息，各自得到一份 chat_key：
    ``<适配器>-<实例>:group_<群号>``。这些 chat_key 指向的是**同一个群**，
    只是回答的人（bot 账号）不同::

        onebot_v11-3639258463:group_1085272119
        onebot_v11-3934926147:group_1085272119
            ↓
        onebot_v11:group_1085272119

    刻意**保留适配器前缀**（``onebot_v11``），这样不同适配器下的同号频道
    不会被误并成同一个「群」。单账号部署（chat_key 形如
    ``onebot_v11-group_1085272119``，没有实例段）原样返回 —— 此时不存在
    可同步的兄弟频道，跨实例同步会自然退化成「只改当前频道」。
    """
    text = str(chat_key or "").strip()
    head, separator, tail = text.partition(":")
    if separator and tail.startswith(("group_", "private_")):
        adapter = head.split("-", 1)[0] if "-" in head else head
        return f"{adapter}{separator}{tail}"
    return text


class AngelMemoryStorage:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY, short_id INTEGER NOT NULL UNIQUE,
                    chat_key TEXT NOT NULL, user_id TEXT NOT NULL DEFAULT '',
                    memory_type TEXT NOT NULL DEFAULT 'episodic', content TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '', tags_json TEXT NOT NULL DEFAULT '[]',
                    importance REAL NOT NULL DEFAULT 0.5, confidence REAL NOT NULL DEFAULT 0.8,
                    access_count INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
                    source TEXT NOT NULL DEFAULT 'manual', created_at REAL NOT NULL,
                    updated_at REAL NOT NULL, last_accessed_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memories_scope
                    ON memories(chat_key, user_id, status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY, short_id INTEGER NOT NULL UNIQUE,
                    chat_key TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]', source TEXT NOT NULL DEFAULT 'agent',
                    created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_notes_scope ON notes(chat_key, updated_at DESC);
                CREATE TABLE IF NOT EXISTS user_profiles (
                    chat_key TEXT NOT NULL, user_id TEXT NOT NULL, display_name TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '', attributes_json TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL, PRIMARY KEY(chat_key, user_id)
                );
                CREATE TABLE IF NOT EXISTS soul_states (
                    chat_key TEXT PRIMARY KEY, recall_depth REAL NOT NULL DEFAULT 0.5,
                    impression_depth REAL NOT NULL DEFAULT 0.5, expression_desire REAL NOT NULL DEFAULT 0.5,
                    creativity REAL NOT NULL DEFAULT 0.5, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS state (
                    state_key TEXT PRIMARY KEY, state_value TEXT NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS favorability (
                    chat_key TEXT NOT NULL, user_id TEXT NOT NULL, display_name TEXT NOT NULL DEFAULT '',
                    stage TEXT NOT NULL DEFAULT '中立', stage_entered_at REAL NOT NULL DEFAULT 0,
                    pos_weight REAL NOT NULL DEFAULT 0, neg_weight REAL NOT NULL DEFAULT 0,
                    pos_kinds_json TEXT NOT NULL DEFAULT '[]', neg_kinds_json TEXT NOT NULL DEFAULT '[]',
                    score INTEGER NOT NULL DEFAULT 0, summary TEXT NOT NULL DEFAULT '',
                    interaction_hint TEXT NOT NULL DEFAULT '', tags_json TEXT NOT NULL DEFAULT '[]',
                    last_reason TEXT NOT NULL DEFAULT '', last_kind TEXT NOT NULL DEFAULT '',
                    last_adjust_at REAL NOT NULL DEFAULT 0, last_event_at REAL NOT NULL DEFAULT 0,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, last_interaction_at REAL NOT NULL,
                    PRIMARY KEY(chat_key, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_favor_scope ON favorability(chat_key, score DESC);
                CREATE TABLE IF NOT EXISTS favorability_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_key TEXT NOT NULL, user_id TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT '', label TEXT NOT NULL DEFAULT '',
                    polarity INTEGER NOT NULL DEFAULT 0, severity INTEGER NOT NULL DEFAULT 0,
                    weight REAL NOT NULL DEFAULT 0, evidence TEXT NOT NULL DEFAULT '',
                    stage_before TEXT NOT NULL DEFAULT '', stage_after TEXT NOT NULL DEFAULT '',
                    delta INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '',
                    score_after INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_favor_events
                    ON favorability_events(chat_key, user_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS facts (
                    id TEXT PRIMARY KEY, short_id INTEGER NOT NULL UNIQUE,
                    chat_key TEXT NOT NULL, user_id TEXT NOT NULL DEFAULT '',
                    subject TEXT NOT NULL DEFAULT '', attribute TEXT NOT NULL DEFAULT '',
                    value TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0.8,
                    source TEXT NOT NULL DEFAULT 'auto', status TEXT NOT NULL DEFAULT 'active',
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(chat_key, user_id, subject, attribute)
                );
                CREATE INDEX IF NOT EXISTS idx_facts_scope
                    ON facts(chat_key, user_id, status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS digests (
                    id TEXT PRIMARY KEY, chat_key TEXT NOT NULL,
                    window_start INTEGER NOT NULL DEFAULT 0, window_end INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '', tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_digests_scope ON digests(chat_key, window_end DESC);
                """
            )
            self._migrate_schema(connection)
            try:
                connection.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                        memory_id UNINDEXED, chat_key UNINDEXED, search_text, tokenize='unicode61');
                    CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(
                        note_id UNINDEXED, chat_key UNINDEXED, search_text, tokenize='unicode61');
                    """
                )
            except sqlite3.OperationalError:
                self._set_state(connection, "fts_available", "0")
            else:
                self._set_state(connection, "fts_available", "1")

    @staticmethod
    def _migrate_schema(connection: sqlite3.Connection) -> None:
        """老库平滑升级：补上后加的列，不动既有数据。"""
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(memories)")}
        if "min_favor" not in columns:
            connection.execute(
                "ALTER TABLE memories ADD COLUMN min_favor INTEGER NOT NULL DEFAULT 0"
            )

        favor_columns = {row["name"] for row in connection.execute("PRAGMA table_info(favorability)")}
        favor_additions = (
            ("stage", "TEXT NOT NULL DEFAULT '中立'"),
            ("stage_entered_at", "REAL NOT NULL DEFAULT 0"),
            ("pos_weight", "REAL NOT NULL DEFAULT 0"),
            ("neg_weight", "REAL NOT NULL DEFAULT 0"),
            ("pos_kinds_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("neg_kinds_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("last_kind", "TEXT NOT NULL DEFAULT ''"),
            ("last_event_at", "REAL NOT NULL DEFAULT 0"),
            ("event_count", "INTEGER NOT NULL DEFAULT 0"),
        )
        for name, ddl in favor_additions:
            if name not in favor_columns:
                connection.execute(f"ALTER TABLE favorability ADD COLUMN {name} {ddl}")

        event_columns = {row["name"] for row in connection.execute("PRAGMA table_info(favorability_events)")}
        event_additions = (
            ("kind", "TEXT NOT NULL DEFAULT ''"),
            ("label", "TEXT NOT NULL DEFAULT ''"),
            ("polarity", "INTEGER NOT NULL DEFAULT 0"),
            ("severity", "INTEGER NOT NULL DEFAULT 0"),
            ("weight", "REAL NOT NULL DEFAULT 0"),
            ("evidence", "TEXT NOT NULL DEFAULT ''"),
            ("stage_before", "TEXT NOT NULL DEFAULT ''"),
            ("stage_after", "TEXT NOT NULL DEFAULT ''"),
        )
        for name, ddl in event_additions:
            if name not in event_columns:
                connection.execute(f"ALTER TABLE favorability_events ADD COLUMN {name} {ddl}")

        # 老库只有裸分数：按分数回填阶段，并把分数差额折算成阶段内证据
        if "stage" not in favor_columns:
            for row in connection.execute("SELECT chat_key,user_id,score FROM favorability").fetchall():
                score = int(row["score"] or 0)
                if score == 0:
                    continue
                connection.execute(
                    "UPDATE favorability SET stage=?,stage_entered_at=?,pos_weight=?,neg_weight=?,"
                    "last_kind='',event_count=CASE WHEN event_count>0 THEN event_count ELSE 1 END,"
                    "updated_at=updated_at WHERE chat_key=? AND user_id=?",
                    (
                        score_to_stage(score),
                        float(row["created_at"] if "created_at" in row.keys() else 0) or 0.0,
                        float(max(0, score)) / 20.0,
                        float(max(0, -score)) / 20.0,
                        row["chat_key"],
                        row["user_id"],
                    ),
                )

    @staticmethod
    def _set_state(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            "INSERT INTO state(state_key,state_value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=excluded.updated_at",
            (key, value, time.time()),
        )

    @staticmethod
    def _fts_enabled(connection: sqlite3.Connection) -> bool:
        row = connection.execute("SELECT state_value FROM state WHERE state_key='fts_available'").fetchone()
        return row is None or row["state_value"] == "1"

    @staticmethod
    def _next_short_id(connection: sqlite3.Connection, table: str) -> int:
        row = connection.execute(f"SELECT COALESCE(MAX(short_id),0)+1 AS next_id FROM {table}").fetchone()
        return int(row["next_id"])

    @staticmethod
    def _resolve_row(connection: sqlite3.Connection, table: str, identifier: str | int) -> sqlite3.Row | None:
        value = str(identifier).strip()
        if value.isdigit():
            return connection.execute(f"SELECT * FROM {table} WHERE short_id=?", (int(value),)).fetchone()
        return connection.execute(f"SELECT * FROM {table} WHERE id=?", (value,)).fetchone()

    def add_memory(
        self,
        *,
        chat_key: str,
        content: str,
        summary: str = "",
        tags: Iterable[str] | None = None,
        importance: float = 0.5,
        confidence: float = 0.8,
        memory_type: str = "episodic",
        user_id: str = "",
        source: str = "manual",
        created_at: float | None = None,
        min_favor: int = 0,
    ) -> MemoryRecord:
        content = str(content).strip()
        if not content:
            raise ValueError("Memory content cannot be empty")
        timestamp = float(created_at or time.time())
        tag_list = normalize_tags(tags)
        memory_id = uuid.uuid4().hex
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            short_id = self._next_short_id(connection, "memories")
            connection.execute(
                """
                INSERT INTO memories(
                    id,short_id,chat_key,user_id,memory_type,content,summary,tags_json,
                    importance,confidence,source,created_at,updated_at,last_accessed_at,min_favor
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    memory_id, short_id, chat_key, user_id, memory_type, content, str(summary).strip(),
                    json.dumps(tag_list, ensure_ascii=False), clamp(importance), clamp(confidence), source,
                    timestamp, timestamp, timestamp, max(0, int(min_favor)),
                ),
            )
            if self._fts_enabled(connection):
                connection.execute(
                    "INSERT INTO memory_fts(memory_id,chat_key,search_text) VALUES(?,?,?)",
                    (memory_id, chat_key, search_text(content, summary, " ".join(tag_list))),
                )
            row = connection.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return self.memory_from_row(row)

    def update_memory(self, identifier: str | int, **changes: Any) -> MemoryRecord | None:
        if changes.get("content") is not None and not str(changes["content"]).strip():
            raise ValueError("Memory content cannot be empty")
        with self.connect() as connection:
            row = self._resolve_row(connection, "memories", identifier)
            if row is None:
                return None
            values = dict(row)
            for key in ("content", "summary", "status"):
                if changes.get(key) is not None:
                    values[key] = str(changes[key]).strip()
            if values["status"] not in {"active", "archived"}:
                raise ValueError("Memory status must be active or archived")
            tags = normalize_tags(changes["tags"]) if changes.get("tags") is not None else json.loads(values["tags_json"])
            if changes.get("importance") is not None:
                values["importance"] = clamp(changes["importance"])
            if changes.get("confidence") is not None:
                values["confidence"] = clamp(changes["confidence"])
            if changes.get("min_favor") is not None:
                values["min_favor"] = max(0, int(changes["min_favor"]))
            values["updated_at"] = time.time()
            connection.execute(
                """
                UPDATE memories SET content=?,summary=?,tags_json=?,importance=?,confidence=?,status=?,
                    min_favor=?,updated_at=? WHERE id=?
                """,
                (
                    values["content"], values["summary"], json.dumps(tags, ensure_ascii=False),
                    values["importance"], values["confidence"], values["status"],
                    int(values.get("min_favor", 0) or 0), values["updated_at"], values["id"],
                ),
            )
            if self._fts_enabled(connection):
                connection.execute("DELETE FROM memory_fts WHERE memory_id=?", (values["id"],))
                connection.execute(
                    "INSERT INTO memory_fts(memory_id,chat_key,search_text) VALUES(?,?,?)",
                    (values["id"], values["chat_key"], search_text(values["content"], values["summary"], " ".join(tags))),
                )
            updated = connection.execute("SELECT * FROM memories WHERE id=?", (values["id"],)).fetchone()
        return self.memory_from_row(updated)

    def get_memory(self, identifier: str | int) -> MemoryRecord | None:
        with self.connect() as connection:
            row = self._resolve_row(connection, "memories", identifier)
        return self.memory_from_row(row) if row else None

    def delete_memory(self, identifier: str | int) -> bool:
        with self.connect() as connection:
            row = self._resolve_row(connection, "memories", identifier)
            if row is None:
                return False
            connection.execute("DELETE FROM memories WHERE id=?", (row["id"],))
            if self._fts_enabled(connection):
                connection.execute("DELETE FROM memory_fts WHERE memory_id=?", (row["id"],))
        return True

    def search_memories(
        self,
        *,
        chat_key: str,
        query: str,
        user_id: str = "",
        limit: int = 6,
        include_shared: bool = True,
        min_favor_ceiling: int | None = None,
    ) -> list[MemoryRecord]:
        """检索记忆。

        min_favor_ceiling 非空时，只返回 min_favor <= 该值的记忆（好感度门控）；
        传 None 表示不做门控，把全部分数段的记忆都取回来由调用方自行分流。
        """
        limit = max(1, min(int(limit), 50))
        query_match = match_query(query)
        favor_clause = ""
        favor_params: list[Any] = []
        if min_favor_ceiling is not None:
            favor_clause = " AND m.min_favor<=?"
            favor_params = [max(-1000000, int(min_favor_ceiling))]
        with self.connect() as connection:
            rows: Sequence[sqlite3.Row] = []
            if query_match and self._fts_enabled(connection):
                scope = "(m.user_id='' OR m.user_id=?)" if user_id and include_shared else "m.user_id=?"
                try:
                    rows = connection.execute(
                        f"""
                        SELECT m.* FROM memory_fts JOIN memories m ON m.id=memory_fts.memory_id
                        WHERE memory_fts MATCH ? AND m.chat_key=? AND m.status='active' AND {scope}{favor_clause}
                        ORDER BY bm25(memory_fts) ASC,m.importance DESC LIMIT ?
                        """,
                        (query_match, chat_key, user_id, *favor_params, limit * 3),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows:
                rows = self._fallback_search(
                    connection,
                    chat_key,
                    query,
                    user_id,
                    limit * 3,
                    include_shared,
                    min_favor_ceiling=min_favor_ceiling,
                )
            now = time.time()
            query_set = set(search_tokens(query))
            scored: list[tuple[float, sqlite3.Row]] = []
            for row in rows:
                candidate = set(search_tokens(f"{row['content']} {row['summary']} {row['tags_json']}"))
                overlap = len(query_set & candidate) / max(1, len(query_set))
                age_days = max(0.0, (now - float(row["updated_at"])) / 86400.0)
                score = (
                    overlap * 0.58
                    + float(row["importance"]) * 0.28
                    + math.exp(-age_days / 120.0) * 0.08
                    + float(row["confidence"]) * 0.06
                )
                scored.append((score, row))
            scored.sort(key=lambda item: item[0], reverse=True)
            selected = [row for _, row in scored[:limit]]
            for row in selected:
                connection.execute(
                    "UPDATE memories SET access_count=access_count+1,last_accessed_at=? WHERE id=?",
                    (now, row["id"]),
                )
        return [self.memory_from_row(row) for row in selected]

    def list_memories(self, *, chat_key: str, status: str = "active", limit: int = 100, offset: int = 0) -> list[MemoryRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM memories WHERE chat_key=? AND status=?
                ORDER BY importance DESC,updated_at DESC LIMIT ? OFFSET ?
                """,
                (chat_key, status, max(1, min(limit, 500)), max(0, offset)),
            ).fetchall()
        return [self.memory_from_row(row) for row in rows]

    def find_similar_memory(self, *, chat_key: str, content: str, user_id: str = "") -> MemoryRecord | None:
        source = set(search_tokens(content))
        for memory in self.search_memories(
            chat_key=chat_key,
            query=content,
            user_id=user_id,
            limit=3,
            include_shared=False,
        ):
            candidate = set(search_tokens(memory.content))
            if len(source & candidate) / max(1, len(source | candidate)) >= 0.72:
                return memory
        return None

    @staticmethod
    def _fallback_search(
        connection: sqlite3.Connection,
        chat_key: str,
        query: str,
        user_id: str,
        limit: int,
        include_shared: bool,
        min_favor_ceiling: int | None = None,
    ) -> Sequence[sqlite3.Row]:
        tokens = search_tokens(query)[:12]
        if not tokens:
            return []
        scope = "(user_id='' OR user_id=?)" if user_id and include_shared else "user_id=?"
        clauses = " OR ".join("(content LIKE ? OR summary LIKE ? OR tags_json LIKE ?)" for _ in tokens)
        params: list[Any] = [chat_key, user_id]
        favor_clause = ""
        if min_favor_ceiling is not None:
            favor_clause = " AND min_favor<=?"
        for token in tokens:
            value = f"%{token}%"
            params.extend([value, value, value])
        if min_favor_ceiling is not None:
            params.append(max(-1000000, int(min_favor_ceiling)))
        params.append(limit)
        return connection.execute(
            f"SELECT * FROM memories WHERE chat_key=? AND status='active' AND {scope}"
            f"{favor_clause} AND ({clauses}) LIMIT ?",
            params,
        ).fetchall()

    def add_note(
        self,
        *,
        chat_key: str,
        title: str,
        content: str,
        tags: Iterable[str] | None = None,
        source: str = "agent",
    ) -> NoteRecord:
        title = str(title).strip()
        content = str(content).strip()
        if not title or not content:
            raise ValueError("Note title and content cannot be empty")
        timestamp = time.time()
        note_id = uuid.uuid4().hex
        tag_list = normalize_tags(tags)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            short_id = self._next_short_id(connection, "notes")
            connection.execute(
                "INSERT INTO notes(id,short_id,chat_key,title,content,tags_json,source,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    note_id, short_id, chat_key, title, content,
                    json.dumps(tag_list, ensure_ascii=False), source, timestamp, timestamp,
                ),
            )
            if self._fts_enabled(connection):
                connection.execute(
                    "INSERT INTO note_fts(note_id,chat_key,search_text) VALUES(?,?,?)",
                    (note_id, chat_key, search_text(title, content, " ".join(tag_list))),
                )
            row = connection.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
        return self.note_from_row(row)

    def get_note(self, identifier: str | int) -> NoteRecord | None:
        with self.connect() as connection:
            row = self._resolve_row(connection, "notes", identifier)
        return self.note_from_row(row) if row else None

    def search_notes(self, *, chat_key: str, query: str, limit: int = 5) -> list[NoteRecord]:
        limit = max(1, min(limit, 30))
        query_match = match_query(query)
        with self.connect() as connection:
            rows: Sequence[sqlite3.Row] = []
            if query_match and self._fts_enabled(connection):
                try:
                    rows = connection.execute(
                        """
                        SELECT n.* FROM note_fts JOIN notes n ON n.id=note_fts.note_id
                        WHERE note_fts MATCH ? AND n.chat_key=?
                        ORDER BY bm25(note_fts) ASC,n.updated_at DESC LIMIT ?
                        """,
                        (query_match, chat_key, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows:
                like = f"%{query.strip()}%"
                rows = connection.execute(
                    """
                    SELECT * FROM notes WHERE chat_key=? AND (title LIKE ? OR content LIKE ? OR tags_json LIKE ?)
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (chat_key, like, like, like, limit),
                ).fetchall()
        return [self.note_from_row(row) for row in rows]

    def list_notes(self, *, chat_key: str, limit: int = 100, offset: int = 0) -> list[NoteRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM notes WHERE chat_key=? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (chat_key, max(1, min(limit, 500)), max(0, offset)),
            ).fetchall()
        return [self.note_from_row(row) for row in rows]

    def delete_note(self, identifier: str | int) -> bool:
        with self.connect() as connection:
            row = self._resolve_row(connection, "notes", identifier)
            if row is None:
                return False
            connection.execute("DELETE FROM notes WHERE id=?", (row["id"],))
            if self._fts_enabled(connection):
                connection.execute("DELETE FROM note_fts WHERE note_id=?", (row["id"],))
        return True

    def reset_channel(self, chat_key: str) -> dict[str, int]:
        chat_key = str(chat_key).strip()
        if not chat_key:
            raise ValueError("chat_key cannot be empty")
        counts = {"memories": 0, "notes": 0, "profiles": 0, "soul_states": 0, "favorability": 0, "facts": 0, "digests": 0}
        with self.connect() as connection:
            if self._fts_enabled(connection):
                connection.execute(
                    "DELETE FROM memory_fts WHERE memory_id IN (SELECT id FROM memories WHERE chat_key=?)",
                    (chat_key,),
                )
                connection.execute(
                    "DELETE FROM note_fts WHERE note_id IN (SELECT id FROM notes WHERE chat_key=?)",
                    (chat_key,),
                )
            counts["memories"] = connection.execute("DELETE FROM memories WHERE chat_key=?", (chat_key,)).rowcount
            counts["notes"] = connection.execute("DELETE FROM notes WHERE chat_key=?", (chat_key,)).rowcount
            counts["profiles"] = connection.execute("DELETE FROM user_profiles WHERE chat_key=?", (chat_key,)).rowcount
            counts["soul_states"] = connection.execute("DELETE FROM soul_states WHERE chat_key=?", (chat_key,)).rowcount
            counts["favorability"] = connection.execute(
                "DELETE FROM favorability WHERE chat_key=?", (chat_key,)
            ).rowcount
            connection.execute("DELETE FROM favorability_events WHERE chat_key=?", (chat_key,))
            counts["facts"] = connection.execute("DELETE FROM facts WHERE chat_key=?", (chat_key,)).rowcount
            counts["digests"] = connection.execute("DELETE FROM digests WHERE chat_key=?", (chat_key,)).rowcount
        return counts

    def reset_all(self) -> dict[str, int]:
        counts = {"memories": 0, "notes": 0, "profiles": 0, "soul_states": 0, "favorability": 0, "facts": 0, "digests": 0}
        with self.connect() as connection:
            fts_available = self._fts_enabled(connection)
            if fts_available:
                connection.execute("DELETE FROM memory_fts")
                connection.execute("DELETE FROM note_fts")
            counts["memories"] = connection.execute("DELETE FROM memories").rowcount
            counts["notes"] = connection.execute("DELETE FROM notes").rowcount
            counts["profiles"] = connection.execute("DELETE FROM user_profiles").rowcount
            counts["soul_states"] = connection.execute("DELETE FROM soul_states").rowcount
            counts["favorability"] = connection.execute("DELETE FROM favorability").rowcount
            connection.execute("DELETE FROM favorability_events")
            counts["facts"] = connection.execute("DELETE FROM facts").rowcount
            counts["digests"] = connection.execute("DELETE FROM digests").rowcount
            connection.execute("DELETE FROM state")
            self._set_state(connection, "fts_available", "1" if fts_available else "0")
        return counts

    @staticmethod
    def note_from_row(row: sqlite3.Row) -> NoteRecord:
        return NoteRecord(
            id=row["id"], short_id=int(row["short_id"]), chat_key=row["chat_key"], title=row["title"],
            content=row["content"], tags=json.loads(row["tags_json"] or "[]"), source=row["source"],
            created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
        )

    def get_profile(self, *, chat_key: str, user_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM user_profiles WHERE chat_key=? AND user_id=?",
                (chat_key, user_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "chat_key": row["chat_key"],
            "user_id": row["user_id"],
            "display_name": row["display_name"],
            "summary": row["summary"],
            "attributes": json.loads(row["attributes_json"] or "{}"),
            "updated_at": float(row["updated_at"]),
        }

    def upsert_profile(
        self,
        *,
        chat_key: str,
        user_id: str,
        display_name: str = "",
        summary: str = "",
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_profiles(chat_key,user_id,display_name,summary,attributes_json,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(chat_key,user_id) DO UPDATE SET
                    display_name=excluded.display_name,summary=excluded.summary,
                    attributes_json=excluded.attributes_json,updated_at=excluded.updated_at
                """,
                (
                    chat_key, user_id, display_name, summary,
                    json.dumps(attributes or {}, ensure_ascii=False), time.time(),
                ),
            )
        return self.get_profile(chat_key=chat_key, user_id=user_id) or {}

    def get_soul_state(self, chat_key: str) -> SoulState:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM soul_states WHERE chat_key=?", (chat_key,)).fetchone()
            if row is None:
                timestamp = time.time()
                connection.execute(
                    "INSERT INTO soul_states(chat_key,recall_depth,impression_depth,expression_desire,creativity,updated_at) "
                    "VALUES(?,0.5,0.5,0.5,0.5,?)",
                    (chat_key, timestamp),
                )
                return SoulState(chat_key=chat_key, updated_at=timestamp)
        return SoulState(
            chat_key=row["chat_key"], recall_depth=float(row["recall_depth"]),
            impression_depth=float(row["impression_depth"]), expression_desire=float(row["expression_desire"]),
            creativity=float(row["creativity"]), updated_at=float(row["updated_at"]),
        )

    def update_soul_state(self, chat_key: str, **deltas: float) -> SoulState:
        state = self.get_soul_state(chat_key)
        decay = math.exp(-max(0.0, (time.time() - state.updated_at) / 3600.0) / 72.0)
        for field_name in ("recall_depth", "impression_depth", "expression_desire", "creativity"):
            current = 0.5 + (getattr(state, field_name) - 0.5) * decay
            setattr(state, field_name, clamp(current + float(deltas.get(field_name, 0.0))))
        state.updated_at = time.time()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO soul_states(chat_key,recall_depth,impression_depth,expression_desire,creativity,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(chat_key) DO UPDATE SET
                    recall_depth=excluded.recall_depth,impression_depth=excluded.impression_depth,
                    expression_desire=excluded.expression_desire,creativity=excluded.creativity,
                    updated_at=excluded.updated_at
                """,
                (
                    chat_key, state.recall_depth, state.impression_depth,
                    state.expression_desire, state.creativity, state.updated_at,
                ),
            )
        return state

    def get_state(self, key: str, default: str = "") -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT state_value FROM state WHERE state_key=?", (key,)).fetchone()
        return str(row["state_value"]) if row else default

    def set_state(self, key: str, value: str) -> None:
        with self.connect() as connection:
            self._set_state(connection, key, str(value))

    #: 参与「频道枚举」的数据表
    _CHANNEL_TABLES: tuple[str, ...] = (
        "memories",
        "notes",
        "user_profiles",
        "soul_states",
        "favorability",
        "facts",
        "digests",
    )

    def list_channel_summary(self) -> list[dict[str, Any]]:
        """列出所有频道及其数据量，供 WebUI「填密钥后选频道」用。

        只挑两个用户最关心的维度做展示：好感度档案数、长期记忆条数；
        其余表（笔记 / 画像 / 灵魂状态 / 事实 / 梗概）只用来判断「这个频道有没有数据」。
        """
        counters: dict[str, dict[str, int]] = {}
        with self.connect() as connection:
            for table in self._CHANNEL_TABLES:
                rows = connection.execute(f"SELECT chat_key, COUNT(*) AS n FROM {table} GROUP BY chat_key")
                for row in rows:
                    key = str(row["chat_key"] or "").strip()
                    if not key:
                        continue
                    bucket = counters.setdefault(key, {})
                    bucket[table] = bucket.get(table, 0) + int(row["n"])
        summary = [
            {
                "chat_key": key,
                "favor_count": bucket.get("favorability", 0),
                "memory_count": bucket.get("memories", 0),
                "total_count": sum(bucket.values()),
            }
            for key, bucket in counters.items()
        ]
        summary.sort(key=lambda item: (-item["total_count"], item["chat_key"]))
        return summary

    def maintenance(self, *, archive_after_days: int, archive_threshold: float, max_memories_per_scope: int) -> dict[str, int]:
        now = time.time()
        archived = 0
        pruned = 0
        cutoff = now - max(1, archive_after_days) * 86400
        with self.connect() as connection:
            candidates = connection.execute(
                "SELECT id,importance,confidence,access_count,updated_at FROM memories "
                "WHERE status='active' AND updated_at<?",
                (cutoff,),
            ).fetchall()
            for row in candidates:
                age_days = max(1.0, (now - float(row["updated_at"])) / 86400.0)
                strength = (
                    float(row["importance"]) * 0.55
                    + float(row["confidence"]) * 0.20
                    + min(1.0, math.log1p(int(row["access_count"])) / 4.0) * 0.15
                    + math.exp(-age_days / 365.0) * 0.10
                )
                if strength < archive_threshold:
                    connection.execute("UPDATE memories SET status='archived',updated_at=? WHERE id=?", (now, row["id"]))
                    archived += 1
            scopes = connection.execute(
                "SELECT DISTINCT chat_key,user_id FROM memories WHERE status='active'"
            ).fetchall()
            for scope in scopes:
                overflow = connection.execute(
                    """
                    SELECT id FROM memories WHERE chat_key=? AND user_id=? AND status='active'
                    ORDER BY importance DESC,access_count DESC,updated_at DESC LIMIT -1 OFFSET ?
                    """,
                    (scope["chat_key"], scope["user_id"], max(20, max_memories_per_scope)),
                ).fetchall()
                for row in overflow:
                    connection.execute("UPDATE memories SET status='archived',updated_at=? WHERE id=?", (now, row["id"]))
                    pruned += 1
        return {"archived": archived, "pruned": pruned}

    def export_all(self) -> dict[str, Any]:
        with self.connect() as connection:
            memories = [dict(row) for row in connection.execute("SELECT * FROM memories ORDER BY created_at")]
            notes = [dict(row) for row in connection.execute("SELECT * FROM notes ORDER BY created_at")]
            profiles = [dict(row) for row in connection.execute("SELECT * FROM user_profiles ORDER BY updated_at")]
            soul_states = [dict(row) for row in connection.execute("SELECT * FROM soul_states ORDER BY updated_at")]
            favors = [dict(row) for row in connection.execute("SELECT * FROM favorability ORDER BY score DESC")]
            favor_events = [
                dict(row)
                for row in connection.execute("SELECT * FROM favorability_events ORDER BY id")
            ]
            facts = [dict(row) for row in connection.execute("SELECT * FROM facts ORDER BY created_at")]
            digests = [dict(row) for row in connection.execute("SELECT * FROM digests ORDER BY window_end")]
        for row in memories:
            row["tags"] = json.loads(row.pop("tags_json") or "[]")
        for row in notes:
            row["tags"] = json.loads(row.pop("tags_json") or "[]")
        for row in profiles:
            row["attributes"] = json.loads(row.pop("attributes_json") or "{}")
        for row in favors:
            row["tags"] = json.loads(row.pop("tags_json") or "[]")
            row["pos_kinds"] = json.loads(row.pop("pos_kinds_json") or "[]")
            row["neg_kinds"] = json.loads(row.pop("neg_kinds_json") or "[]")
        for row in digests:
            row["tags"] = json.loads(row.pop("tags_json") or "[]")
        return {
            "version": 3,
            "memories": memories,
            "notes": notes,
            "profiles": profiles,
            "soul_states": soul_states,
            "favorability": favors,
            "favorability_events": favor_events,
            "facts": facts,
            "digests": digests,
        }

    def import_memories(self, memories: Iterable[dict[str, Any]], *, default_chat_key: str = "") -> dict[str, int]:
        imported = 0
        skipped = 0
        for item in memories:
            content = str(item.get("content") or item.get("judgment") or item.get("memory") or "").strip()
            chat_key = str(item.get("chat_key") or item.get("scope") or default_chat_key).strip()
            if not content or not chat_key:
                skipped += 1
                continue
            tags = item.get("tags") or []
            if isinstance(tags, str):
                tags = [tag.strip() for tag in re.split(r"[,;\uFF0C\uFF1B]", tags) if tag.strip()]
            memory_scope = str(item.get("memory_scope") or "").strip()
            if memory_scope and memory_scope != "public":
                tags = [*tags, f"astrbot-scope:{memory_scope}"]
            raw_importance = item.get("importance", item.get("weight", item.get("strength", 0.5)))
            importance = 0.5 if raw_importance in (None, "") else float(raw_importance)
            if importance > 1.0:
                importance /= 100.0
            self.add_memory(
                chat_key=chat_key,
                user_id=str(item.get("user_id") or ""),
                content=content,
                summary=str(item.get("summary") or item.get("reasoning") or ""),
                tags=tags,
                importance=importance,
                confidence=float(item.get("confidence", 0.8) or 0.8),
                memory_type=str(item.get("memory_type") or item.get("type") or "episodic"),
                source="astrbot_import",
                created_at=float(item.get("created_at") or item.get("timestamp") or time.time()),
            )
            imported += 1
        return {"imported": imported, "skipped": skipped}

    # ------------------------------------------------------------ 好感度

    def get_favor(self, *, chat_key: str, user_id: str) -> FavorProfile | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM favorability WHERE chat_key=? AND user_id=?",
                (chat_key, user_id),
            ).fetchone()
        return self.favor_from_row(row) if row else None

    def get_or_create_favor(
        self,
        *,
        chat_key: str,
        user_id: str,
        display_name: str = "",
        default_stage: str = DEFAULT_STAGE,
    ) -> FavorProfile:
        profile = self.get_favor(chat_key=chat_key, user_id=user_id)
        if profile is not None:
            return profile
        now = time.time()
        stage = clamp_stage(default_stage)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO favorability(
                    chat_key,user_id,display_name,stage,stage_entered_at,score,summary,interaction_hint,
                    tags_json,last_reason,last_kind,last_adjust_at,last_event_at,event_count,
                    created_at,updated_at,last_interaction_at
                ) VALUES(?,?,?,?,?,0,'','','[]','','',0,0,0,?,?,?)
                """,
                (chat_key, user_id, str(display_name or "").strip(), stage, now, now, now, now),
            )
        return self.get_favor(chat_key=chat_key, user_id=user_id) or FavorProfile(
            chat_key=chat_key, user_id=user_id, display_name=str(display_name or "").strip(),
            stage=stage, stage_entered_at=now, created_at=now, updated_at=now, last_interaction_at=now,
        )

    def touch_favor(
        self,
        *,
        chat_key: str,
        user_id: str,
        display_name: str = "",
        auto_enroll: bool = False,
        now: float | None = None,
    ) -> bool:
        """更新最近互动时间与（空）昵称。

        `auto_enroll=True` 时档案不存在会**当场建档**（「聊过就进榜」模式）：
        新档案落在默认阶段（中立）、零证据，**阶段跃迁仍然只由关系事件驱动**，
        所以这不改变状态机语义，只是让排行榜先有花名册。
        默认 `False` 保持原行为：只在档案已存在时更新，不会凭空建档。

        Returns:
            bool: True 表示本次新建了档案。
        """
        if not str(chat_key or "").strip() or not str(user_id or "").strip():
            return False
        timestamp = float(now or time.time())
        created = False
        with self.connect() as connection:
            row = connection.execute(
                "SELECT user_id FROM favorability WHERE chat_key=? AND user_id=?",
                (chat_key, user_id),
            ).fetchone()
            if row is None:
                if not auto_enroll:
                    return False
                self._ensure_favor_row(connection, chat_key, user_id, timestamp)
                created = True
            connection.execute(
                "UPDATE favorability SET last_interaction_at=? WHERE chat_key=? AND user_id=?",
                (timestamp, chat_key, user_id),
            )
            if display_name:
                connection.execute(
                    "UPDATE favorability SET display_name=? WHERE chat_key=? AND user_id=? "
                    "AND (display_name='' OR display_name IS NULL)",
                    (str(display_name).strip(), chat_key, user_id),
                )
        return created

    def _ensure_favor_row(self, connection: sqlite3.Connection, chat_key: str, user_id: str, now: float) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM favorability WHERE chat_key=? AND user_id=?",
            (chat_key, user_id),
        ).fetchone()
        if row is None:
            connection.execute(
                """
                INSERT INTO favorability(
                    chat_key,user_id,display_name,stage,stage_entered_at,score,summary,interaction_hint,
                    tags_json,last_reason,last_kind,last_adjust_at,last_event_at,event_count,
                    created_at,updated_at,last_interaction_at
                ) VALUES(?,?,'',?,?,0,'','','[]','','',0,0,0,?,?,?)
                """,
                (chat_key, user_id, DEFAULT_STAGE, now, now, now, now),
            )
            row = connection.execute(
                "SELECT * FROM favorability WHERE chat_key=? AND user_id=?",
                (chat_key, user_id),
            ).fetchone()
        return row

    @staticmethod
    def _write_favor_state(
        connection: sqlite3.Connection,
        *,
        chat_key: str,
        user_id: str,
        stage: str,
        stage_entered_at: float,
        pos_weight: float,
        neg_weight: float,
        pos_kinds: list[str],
        neg_kinds: list[str],
        score: int,
        last_kind: str,
        last_event_at: float,
        event_count: int,
        now: float,
    ) -> None:
        connection.execute(
            """
            UPDATE favorability SET stage=?,stage_entered_at=?,pos_weight=?,neg_weight=?,
                pos_kinds_json=?,neg_kinds_json=?,score=?,last_kind=?,last_event_at=?,event_count=?,
                updated_at=?,last_interaction_at=?
            WHERE chat_key=? AND user_id=?
            """,
            (
                clamp_stage(stage), float(stage_entered_at), float(pos_weight), float(neg_weight),
                json.dumps(list(pos_kinds), ensure_ascii=False), json.dumps(list(neg_kinds), ensure_ascii=False),
                int(score), str(last_kind or ""), float(last_event_at), int(event_count),
                float(now), float(now), chat_key, user_id,
            ),
        )

    def record_favor_event(
        self,
        *,
        chat_key: str,
        user_id: str,
        kind: str,
        evidence: str,
        severity: int = 2,
        display_name: str = "",
        summary: str = "",
        interaction_hint: str = "",
        tags: Iterable[str] | None = None,
        limits: EventLimits | None = None,
        rules: TransitionRules | None = None,
        max_events: int = 12,
        now: float | None = None,
    ) -> tuple[FavorProfile, EventOutcome, StageDecision]:
        """记录一次关系事件，并按状态机规则决定是否跃迁阶段。

        这是好感度唯一的写入口：事件是权威来源，`favorability` 行只是投影结果。
        """
        timestamp = float(now or time.time())
        active_limits = limits or EventLimits()
        active_rules = rules or TransitionRules()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._ensure_favor_row(connection, chat_key, user_id, timestamp)
            stage_before = clamp_stage(row["stage"])
            entered_at = float(row["stage_entered_at"] or row["created_at"] or timestamp)
            last_event_at = float(row["last_event_at"] or 0)

            day_start = timestamp - (timestamp % 86400)
            totals = connection.execute(
                "SELECT COUNT(*) AS total,"
                " SUM(CASE WHEN polarity>0 THEN 1 ELSE 0 END) AS pos,"
                " SUM(CASE WHEN polarity<0 THEN 1 ELSE 0 END) AS neg "
                "FROM favorability_events WHERE chat_key=? AND user_id=? AND created_at>=?",
                (chat_key, user_id, day_start),
            ).fetchone()
            events_today = int(totals["total"] or 0)
            positive_today = int(totals["pos"] or 0)
            negative_today = int(totals["neg"] or 0)

            normalized_kind = str(kind or "").strip().lower()
            same_kind = connection.execute(
                "SELECT COUNT(*) AS c FROM favorability_events "
                "WHERE chat_key=? AND user_id=? AND kind=? AND created_at>=?",
                (chat_key, user_id, normalized_kind, entered_at),
            ).fetchone()
            same_kind_count = int(same_kind["c"] or 0)

            outcome = evaluate_event(
                kind=normalized_kind,
                severity=severity,
                evidence=evidence,
                stage=stage_before,
                same_kind_count=same_kind_count,
                events_today=events_today,
                positive_today=positive_today,
                negative_today=negative_today,
                last_event_at=last_event_at,
                now=timestamp,
                limits=active_limits,
            )
            if not outcome.applied:
                current = self.favor_from_row(row)
                return current, outcome, StageDecision(stage=stage_before)

            pos_weight = float(row["pos_weight"] or 0)
            neg_weight = float(row["neg_weight"] or 0)
            pos_kinds = list(json.loads(row["pos_kinds_json"] or "[]"))
            neg_kinds = list(json.loads(row["neg_kinds_json"] or "[]"))
            if outcome.polarity > 0:
                pos_weight += outcome.weight
                if normalized_kind not in pos_kinds:
                    pos_kinds.append(normalized_kind)
            else:
                neg_weight += outcome.weight
                if normalized_kind not in neg_kinds:
                    neg_kinds.append(normalized_kind)

            decision = decide_stage(
                stage=stage_before,
                pos_weight=pos_weight,
                neg_weight=neg_weight,
                pos_kinds=len(pos_kinds),
                entered_at=entered_at,
                now=timestamp,
                rules=active_rules,
            )
            stage_after = stage_before
            if decision.reset_evidence:
                stage_after = decision.stage
                entered_at = timestamp
                carried = float(decision.carried)
                if decision.direction > 0:
                    pos_weight, neg_weight = max(0.0, carried), 0.0
                    pos_kinds, neg_kinds = [], []
                else:
                    pos_weight, neg_weight = 0.0, max(0.0, -carried)
                    pos_kinds, neg_kinds = [], []

            score = project_score(stage=stage_after, pos_weight=pos_weight, neg_weight=neg_weight)
            merged_tags = list(json.loads(row["tags_json"] or "[]"))
            if tags:
                merged_tags = normalize_tags([*merged_tags, *tags])
            connection.execute(
                "UPDATE favorability SET display_name=?,summary=?,interaction_hint=?,tags_json=?,last_reason=?,"
                "last_adjust_at=? WHERE chat_key=? AND user_id=?",
                (
                    str(display_name or "").strip() or row["display_name"],
                    str(summary or "").strip() or row["summary"],
                    str(interaction_hint or "").strip() or row["interaction_hint"],
                    json.dumps(merged_tags, ensure_ascii=False),
                    " ".join(str(evidence or "").split())[:active_limits.max_evidence_chars],
                    timestamp, chat_key, user_id,
                ),
            )
            self._write_favor_state(
                connection,
                chat_key=chat_key,
                user_id=user_id,
                stage=stage_after,
                stage_entered_at=entered_at,
                pos_weight=pos_weight,
                neg_weight=neg_weight,
                pos_kinds=pos_kinds,
                neg_kinds=neg_kinds,
                score=score,
                last_kind=normalized_kind,
                last_event_at=timestamp,
                event_count=int(row["event_count"] or 0) + 1,
                now=timestamp,
            )
            connection.execute(
                "INSERT INTO favorability_events(chat_key,user_id,kind,label,polarity,severity,weight,"
                "evidence,stage_before,stage_after,delta,reason,score_after,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    chat_key, user_id, normalized_kind, kind_label(normalized_kind), outcome.polarity,
                    int(max(1, min(active_limits.max_severity, int(severity)))),
                    float(outcome.weight), " ".join(str(evidence or "").split())[:active_limits.max_evidence_chars],
                    stage_before, stage_after, 1 if outcome.polarity > 0 else -1,
                    " ".join(str(evidence or "").split())[:200], score, timestamp,
                ),
            )
            connection.execute(
                "DELETE FROM favorability_events WHERE chat_key=? AND user_id=? AND id NOT IN "
                "(SELECT id FROM favorability_events WHERE chat_key=? AND user_id=? ORDER BY id DESC LIMIT ?)",
                (chat_key, user_id, chat_key, user_id, max(1, int(max_events))),
            )
            updated = connection.execute(
                "SELECT * FROM favorability WHERE chat_key=? AND user_id=?",
                (chat_key, user_id),
            ).fetchone()
        return self.favor_from_row(updated), outcome, decision

    def set_favor_stage(
        self,
        *,
        chat_key: str,
        user_id: str,
        stage: str,
        reason: str = "",
        display_name: str = "",
        summary: str = "",
        interaction_hint: str = "",
        interaction_hint_override: bool = False,
        tags: Iterable[str] | None = None,
        max_events: int = 12,
        last_kind: str = "manual_set",
        label: str = "人工设定",
        now: float | None = None,
    ) -> FavorProfile:
        """直接设定阶段（覆盖状态机），会清空当前阶段内的证据。

        `last_kind` / `label` 用于区分调用来源：人工设定走 `manual_set`，
        AI 自主提升走 `ai_promote`（后者会被每日次数上限单独统计）。

        `interaction_hint_override=True` 表示调用方**显式**给了互动基调：
        此时按原样写入，空串即「清空、恢复按阶段自动」。默认 False 时，
        空串是「不修改」；但阶段发生变化时空串仍会清空旧基调 —— 旧基调属于
        旧阶段，留着会在注入时盖掉 `stage_guide(新阶段)`，表现成「改了阶段
        但说话还是旧态度」。
        """
        timestamp = float(now or time.time())
        kind_key = str(last_kind or "manual_set").strip().lower() or "manual_set"
        kind_label_text = str(label or "").strip() or "人工设定"
        target_stage = clamp_stage(stage)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._ensure_favor_row(connection, chat_key, user_id, timestamp)
            stage_before = clamp_stage(row["stage"])
            merged_tags = list(json.loads(row["tags_json"] or "[]"))
            if tags:
                merged_tags = normalize_tags([*merged_tags, *tags])
            # 互动基调是「阶段之上的补充说明」。阶段一变，旧基调就属于旧阶段了：
            # 继续留着会在注入时盖掉 stage_guide(新阶段)，表现成「面板改了阶段，
            # 但 AI 说话还是旧态度」。所以阶段发生变化且没给新基调时，必须清空。
            hint_text = str(interaction_hint or "").strip()
            if not interaction_hint_override and not hint_text and target_stage == stage_before:
                hint_text = str(row["interaction_hint"] or "")
            score = project_score(stage=target_stage, pos_weight=0.0, neg_weight=0.0)
            connection.execute(
                "UPDATE favorability SET display_name=?,summary=?,interaction_hint=?,tags_json=?,last_reason=?,"
                "last_adjust_at=? WHERE chat_key=? AND user_id=?",
                (
                    str(display_name or "").strip() or row["display_name"],
                    str(summary or "").strip() or row["summary"],
                    hint_text,
                    json.dumps(merged_tags, ensure_ascii=False),
                    str(reason or "人工设定关系阶段")[:200], timestamp, chat_key, user_id,
                ),
            )
            self._write_favor_state(
                connection,
                chat_key=chat_key,
                user_id=user_id,
                stage=target_stage,
                stage_entered_at=timestamp,
                pos_weight=0.0,
                neg_weight=0.0,
                pos_kinds=[],
                neg_kinds=[],
                score=score,
                last_kind=kind_key,
                last_event_at=timestamp,
                event_count=int(row["event_count"] or 0) + 1,
                now=timestamp,
            )
            connection.execute(
                "INSERT INTO favorability_events(chat_key,user_id,kind,label,polarity,severity,weight,"
                "evidence,stage_before,stage_after,delta,reason,score_after,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    chat_key, user_id, kind_key, kind_label_text, 0, 2, 0.0,
                    str(reason or "人工设定关系阶段")[:200], stage_before, target_stage, 0,
                    str(reason or "人工设定关系阶段")[:200], score, timestamp,
                ),
            )
            connection.execute(
                "DELETE FROM favorability_events WHERE chat_key=? AND user_id=? AND id NOT IN "
                "(SELECT id FROM favorability_events WHERE chat_key=? AND user_id=? ORDER BY id DESC LIMIT ?)",
                (chat_key, user_id, chat_key, user_id, max(1, int(max_events))),
            )
            updated = connection.execute(
                "SELECT * FROM favorability WHERE chat_key=? AND user_id=?",
                (chat_key, user_id),
            ).fetchone()
        return self.favor_from_row(updated)

    def list_favor_scopes(self, *, chat_key: str, user_id: str) -> dict[str, Any]:
        """列出某个用户在各频道下的关系档案，按「同频道其它实例 / 其它频道」分组。

        多账号部署下，同一个群会被多个账号同时接收消息，每个实例各持一份档案。
        面板里只改当前选中的频道时，其它实例回话仍按旧阶段 —— 前端用这份数据
        把「可一并同步的范围」列出来，让管理员一眼看到各实例当前阶段是否一致。
        """
        current = str(chat_key or "").strip()
        base = channel_base(current)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT chat_key,stage,event_count,updated_at FROM favorability WHERE user_id=?",
                (str(user_id or "").strip(),),
            ).fetchall()
            known = [str(row["chat_key"] or "") for row in connection.execute("SELECT DISTINCT chat_key FROM favorability")]
        profiles = {str(row["chat_key"]): row for row in rows}

        def build(key: str) -> dict[str, Any]:
            row = profiles.get(key)
            return {
                "chat_key": key,
                "stage": str(row["stage"]) if row is not None else "",
                "event_count": int(row["event_count"] or 0) if row is not None else 0,
                "has_profile": row is not None,
                "is_current": key == current,
                "updated_at": float(row["updated_at"] or 0) if row is not None else 0.0,
            }

        candidates = sorted({*known, current} - {""})
        instances = [build(key) for key in candidates if channel_base(key) == base]
        others = [build(key) for key in candidates if channel_base(key) != base and key in profiles]
        # 当前频道排最前，其余按档案新旧排，方便前端直接展示
        instances.sort(key=lambda item: (not item["is_current"], -item["updated_at"], item["chat_key"]))
        others.sort(key=lambda item: (-item["updated_at"], item["chat_key"]))
        return {
            "channel_base": base,
            "current": current,
            "user_id": str(user_id or "").strip(),
            "instances": instances,
            "others": others,
        }

    def align_favor_scopes(
        self,
        *,
        dry_run: bool = True,
        max_events: int = 12,
        now: float | None = None,
    ) -> dict[str, Any]:
        """把「同频道其它实例」上的空壳档案对齐到该频道里最有信息量的那份。

        多账号部署下，同一个群会被多个账号同时接收：每个实例都会给发言人自动
        建档（默认阶段、零事件）。管理员在面板里改了其中一个实例的阶段，其它
        实例回话时仍按默认阶段，看起来就是「改了没生效」。本方法用来一次性
        抹平这类历史漂移。

        只覆盖「阶段为默认值**且**没有任何关系事件」的档案，也就是纯自动建档、
        从未被人工设定或事件驱动过的空壳。人工设过或有事件的档案一律不动，
        避免把有意为之的差异抹平。`dry_run=True` 时只返回计划，不写库。

        计划里每条都带 `mode`：`stage` 表示阶段确实要变（会写一条「实例对齐」
        事件）；`profile` 表示阶段本来就一致、只是稳定印象/互动基调/标签没跟上，
        只补文字、不写事件，免得污染事件流水。
        """
        timestamp = float(now or time.time())
        with self.connect() as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT chat_key,user_id,stage,summary,interaction_hint,tags_json,event_count,updated_at "
                    "FROM favorability"
                )
            ]

        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault((channel_base(str(row["chat_key"])), str(row["user_id"])), []).append(row)

        plan: list[dict[str, Any]] = []
        sources: dict[tuple[str, str], dict[str, Any]] = {}
        for group_key, members in groups.items():
            if len(members) < 2:
                continue
            settled = [
                item
                for item in members
                if str(item["stage"]) != DEFAULT_STAGE or int(item["event_count"] or 0) > 0
            ]
            if not settled:
                continue
            source = max(settled, key=lambda item: (int(item["event_count"] or 0), float(item["updated_at"] or 0)))
            sources[group_key] = source
            source_summary = str(source["summary"] or "").strip()
            source_hint = str(source["interaction_hint"] or "").strip()
            source_tags = list(json.loads(source["tags_json"] or "[]"))
            for member in members:
                if str(member["chat_key"]) == str(source["chat_key"]):
                    continue
                if str(member["stage"]) != DEFAULT_STAGE or int(member["event_count"] or 0) > 0:
                    continue
                same_stage = str(member["stage"]) == str(source["stage"])
                # 阶段本来就一致、来源也没有可搬的文字时，这一条无事可做
                if same_stage and not (source_summary or source_hint or source_tags):
                    continue
                plan.append(
                    {
                        "channel_base": group_key[0],
                        "user_id": group_key[1],
                        "chat_key": str(member["chat_key"]),
                        "from_stage": str(member["stage"]),
                        "to_stage": str(source["stage"]),
                        "source_chat_key": str(source["chat_key"]),
                        # stage  = 阶段真的要变，写一条「实例对齐」事件
                        # profile = 阶段本来就一样，只补文字，不写事件
                        "mode": "profile" if same_stage else "stage",
                    }
                )

        if dry_run or not plan:
            return {"dry_run": True, "planned": len(plan), "applied": 0, "items": plan}

        applied = 0
        for item in plan:
            source = sources[(item["channel_base"], item["user_id"])]
            summary = str(source["summary"] or "")
            hint = str(source["interaction_hint"] or "")
            tags = list(json.loads(source["tags_json"] or "[]"))
            if item["mode"] == "profile":
                self.update_favor_profile(
                    chat_key=item["chat_key"],
                    user_id=item["user_id"],
                    summary=summary or None,
                    interaction_hint=hint or None,
                    tags=tags or None,
                    now=timestamp,
                )
            else:
                self.set_favor_stage(
                    chat_key=item["chat_key"],
                    user_id=item["user_id"],
                    stage=str(source["stage"]),
                    reason=f"对齐同频道其它实例档案（来源 {item['source_chat_key']}）",
                    summary=summary,
                    interaction_hint=hint,
                    interaction_hint_override=True,
                    tags=tags,
                    max_events=max_events,
                    last_kind="scope_align",
                    label="实例对齐",
                    now=timestamp,
                )
            applied += 1
        return {"dry_run": False, "planned": len(plan), "applied": applied, "items": plan}

    def update_favor_profile(
        self,
        *,
        chat_key: str,
        user_id: str,
        display_name: str | None = None,
        summary: str | None = None,
        interaction_hint: str | None = None,
        tags: Iterable[str] | None = None,
        now: float | None = None,
    ) -> FavorProfile | None:
        """只改档案的文字描述，不动关系状态。"""
        timestamp = float(now or time.time())
        with self.connect() as connection:
            row = self._ensure_favor_row(connection, chat_key, user_id, timestamp)
            merged_tags = list(json.loads(row["tags_json"] or "[]"))
            if tags is not None:
                merged_tags = normalize_tags([*merged_tags, *tags])
            connection.execute(
                "UPDATE favorability SET display_name=?,summary=?,interaction_hint=?,tags_json=?,updated_at=? "
                "WHERE chat_key=? AND user_id=?",
                (
                    str(display_name).strip() if display_name is not None else row["display_name"],
                    str(summary).strip() if summary is not None else row["summary"],
                    str(interaction_hint).strip() if interaction_hint is not None else row["interaction_hint"],
                    json.dumps(merged_tags, ensure_ascii=False), timestamp, chat_key, user_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM favorability WHERE chat_key=? AND user_id=?",
                (chat_key, user_id),
            ).fetchone()
        return self.favor_from_row(updated)

    def delete_favor(self, *, chat_key: str, user_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT user_id FROM favorability WHERE chat_key=? AND user_id=?",
                (chat_key, user_id),
            ).fetchone()
            if row is None:
                return False
            connection.execute("DELETE FROM favorability WHERE chat_key=? AND user_id=?", (chat_key, user_id))
            connection.execute("DELETE FROM favorability_events WHERE chat_key=? AND user_id=?", (chat_key, user_id))
        return True

    def list_favors(
        self,
        *,
        chat_key: str,
        limit: int = 20,
        offset: int = 0,
        hide_empty: bool = True,
    ) -> list[FavorProfile]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM favorability WHERE chat_key=?", (chat_key,)
            ).fetchall()
        profiles = [self.favor_from_row(row) for row in rows]
        if hide_empty:
            profiles = [profile for profile in profiles if not profile.is_empty()]
        # 阶段优先，其次投影分，最后最近更新
        profiles.sort(
            key=lambda item: (stage_index(item.stage), int(item.score), float(item.updated_at)),
            reverse=True,
        )
        start = max(0, int(offset))
        size = max(1, min(int(limit), 200))
        return profiles[start : start + size]

    def count_favors(self, *, chat_key: str, hide_empty: bool = True) -> int:
        return len(self.list_favors(chat_key=chat_key, limit=200, hide_empty=hide_empty))

    def list_favor_events(self, *, chat_key: str, user_id: str, limit: int = 5) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT kind,label,polarity,severity,weight,evidence,stage_before,stage_after,"
                "delta,reason,score_after,created_at FROM favorability_events "
                "WHERE chat_key=? AND user_id=? ORDER BY id DESC LIMIT ?",
                (chat_key, user_id, max(1, min(int(limit), 100))),
            ).fetchall()
        return [
            {
                "kind": row["kind"],
                "label": row["label"] or row["kind"],
                "polarity": int(row["polarity"] or 0),
                "severity": int(row["severity"] or 0),
                "weight": float(row["weight"] or 0),
                "evidence": row["evidence"] or row["reason"],
                "stage_before": row["stage_before"],
                "stage_after": row["stage_after"],
                "delta": int(row["delta"] or 0),
                "reason": row["reason"],
                "score_after": int(row["score_after"]),
                "created_at": float(row["created_at"]),
            }
            for row in rows
        ]

    def favor_event_totals(self, *, chat_key: str, user_id: str, since_ts: float) -> tuple[int, int, int]:
        """返回 (事件总数, 正向数, 负向数)。"""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total,"
                " SUM(CASE WHEN polarity>0 THEN 1 ELSE 0 END) AS pos,"
                " SUM(CASE WHEN polarity<0 THEN 1 ELSE 0 END) AS neg "
                "FROM favorability_events WHERE chat_key=? AND user_id=? AND created_at>=?",
                (chat_key, user_id, float(since_ts)),
            ).fetchone()
        return int(row["total"] or 0), int(row["pos"] or 0), int(row["neg"] or 0)

    def count_favor_events_by_kind(
        self,
        *,
        chat_key: str,
        user_id: str,
        kind: str,
        since_ts: float = 0.0,
    ) -> int:
        """统计某个用户在指定时间之后、指定事件类型的事件条数。

        用于「AI 自主提升」的每日配额校验（kind='ai_promote'），
        与 `favor_event_totals` 不同：只按类型计数，不看极性。
        """
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM favorability_events "
                "WHERE chat_key=? AND user_id=? AND kind=? AND created_at>=?",
                (chat_key, user_id, str(kind or "").strip().lower(), float(since_ts)),
            ).fetchone()
        return int(row["total"] or 0)

    def erode_favor_evidence(
        self,
        *,
        elapsed_hours: float,
        half_life_hours: float,
        rules: TransitionRules | None = None,
        now: float | None = None,
    ) -> dict[str, int]:
        """随时间衰减阶段内证据，并让长期无互动的关系自然回落一级。

        注意：这里衰减的是**证据权重**，不是分数；分数只是投影，会跟着变。
        """
        timestamp = float(now or time.time())
        active_rules = rules or TransitionRules()
        factor = 0.5 ** (max(0.0, float(elapsed_hours)) / max(1.0, float(half_life_hours)))
        eroded = 0
        demoted = 0
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM favorability WHERE pos_weight>0.01 OR neg_weight>0.01 OR event_count>0"
            ).fetchall()
            for row in rows:
                chat_key = row["chat_key"]
                user_id = row["user_id"]
                pos_weight = float(row["pos_weight"] or 0) * factor
                neg_weight = float(row["neg_weight"] or 0) * factor
                if pos_weight < 0.01:
                    pos_weight = 0.0
                if neg_weight < 0.01:
                    neg_weight = 0.0
                pos_kinds = list(json.loads(row["pos_kinds_json"] or "[]"))
                neg_kinds = list(json.loads(row["neg_kinds_json"] or "[]"))
                stage = clamp_stage(row["stage"])
                entered_at = float(row["stage_entered_at"] or timestamp)
                idle_hours = max(0.0, (timestamp - float(row["last_interaction_at"] or timestamp)) / 3600.0)
                decision = decide_stage(
                    stage=stage,
                    pos_weight=pos_weight,
                    neg_weight=neg_weight,
                    pos_kinds=len(pos_kinds),
                    entered_at=entered_at,
                    now=timestamp,
                    rules=active_rules,
                    allow_idle_demote=True,
                    idle_hours=idle_hours,
                )
                stage_after = stage
                if decision.reset_evidence:
                    stage_after = decision.stage
                    entered_at = timestamp
                    pos_weight = 0.0
                    neg_weight = 0.0
                    pos_kinds, neg_kinds = [], []
                    if decision.direction < 0:
                        demoted += 1
                    connection.execute(
                        "INSERT INTO favorability_events(chat_key,user_id,kind,label,polarity,severity,weight,"
                        "evidence,stage_before,stage_after,delta,reason,score_after,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            chat_key, user_id, "idle_demote", "关系回落", -1, 1, 0.0,
                            decision.reason, stage, stage_after, -1, decision.reason,
                            project_score(stage=stage_after, pos_weight=0.0, neg_weight=0.0), timestamp,
                        ),
                    )
                else:
                    eroded += 1
                score = project_score(stage=stage_after, pos_weight=pos_weight, neg_weight=neg_weight)
                self._write_favor_state(
                    connection,
                    chat_key=chat_key,
                    user_id=user_id,
                    stage=stage_after,
                    stage_entered_at=entered_at,
                    pos_weight=pos_weight,
                    neg_weight=neg_weight,
                    pos_kinds=pos_kinds,
                    neg_kinds=neg_kinds,
                    score=score,
                    last_kind=row["last_kind"],
                    last_event_at=float(row["last_event_at"] or 0),
                    event_count=int(row["event_count"] or 0),
                    now=timestamp,
                )
        return {"eroded": eroded, "demoted": demoted}

    @staticmethod
    def favor_from_row(row: sqlite3.Row) -> FavorProfile:
        keys = row.keys()
        return FavorProfile(
            chat_key=row["chat_key"], user_id=row["user_id"], display_name=row["display_name"],
            stage=clamp_stage(row["stage"]) if "stage" in keys else score_to_stage(int(row["score"])),
            stage_entered_at=float(row["stage_entered_at"]) if "stage_entered_at" in keys else float(row["created_at"]),
            pos_weight=float(row["pos_weight"]) if "pos_weight" in keys else 0.0,
            neg_weight=float(row["neg_weight"]) if "neg_weight" in keys else 0.0,
            pos_kinds=json.loads(row["pos_kinds_json"] or "[]") if "pos_kinds_json" in keys else [],
            neg_kinds=json.loads(row["neg_kinds_json"] or "[]") if "neg_kinds_json" in keys else [],
            score=int(row["score"]), summary=row["summary"], interaction_hint=row["interaction_hint"],
            tags=json.loads(row["tags_json"] or "[]"), last_reason=row["last_reason"],
            last_kind=row["last_kind"] if "last_kind" in keys else "",
            last_adjust_at=float(row["last_adjust_at"]),
            last_event_at=float(row["last_event_at"]) if "last_event_at" in keys else 0.0,
            event_count=int(row["event_count"]) if "event_count" in keys else 0,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]), last_interaction_at=float(row["last_interaction_at"]),
        )

    # ------------------------------------------------------------ 结构化事实

    def upsert_fact(
        self,
        *,
        chat_key: str,
        user_id: str = "",
        subject: str = "",
        attribute: str,
        value: str,
        confidence: float = 0.8,
        source: str = "auto",
        now: float | None = None,
    ) -> FactRecord:
        """按 (chat_key,user_id,subject,attribute) 幂等写入结构化事实。"""
        attribute = str(attribute or "").strip()
        value = " ".join(str(value or "").split())
        if not attribute:
            raise ValueError("Fact attribute cannot be empty")
        if not value:
            raise ValueError("Fact value cannot be empty")
        timestamp = float(now or time.time())
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM facts WHERE chat_key=? AND user_id=? AND subject=? AND attribute=?",
                (chat_key, user_id, str(subject or "").strip(), attribute),
            ).fetchone()
            if existing is None:
                fact_id = uuid.uuid4().hex
                short_id = self._next_short_id(connection, "facts")
                connection.execute(
                    "INSERT INTO facts(id,short_id,chat_key,user_id,subject,attribute,value,confidence,"
                    "source,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'active',?,?)",
                    (
                        fact_id, short_id, chat_key, user_id, str(subject or "").strip(), attribute,
                        value, clamp(confidence), source, timestamp, timestamp,
                    ),
                )
            else:
                fact_id = existing["id"]
                connection.execute(
                    "UPDATE facts SET value=?,confidence=?,source=?,status='active',updated_at=? WHERE id=?",
                    (value, clamp(max(confidence, float(existing["confidence"]))), source, timestamp, fact_id),
                )
            row = connection.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone()
        return self.fact_from_row(row)

    def get_fact(self, identifier: str | int) -> FactRecord | None:
        with self.connect() as connection:
            row = self._resolve_row(connection, "facts", identifier)
        return self.fact_from_row(row) if row else None

    def list_facts(
        self,
        *,
        chat_key: str,
        user_id: str = "",
        limit: int = 20,
        offset: int = 0,
        status: str = "active",
    ) -> list[FactRecord]:
        query = "SELECT * FROM facts WHERE chat_key=?"
        params: list[Any] = [chat_key]
        if user_id:
            query += " AND (user_id=? OR user_id='')"
            params.append(user_id)
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY confidence DESC, updated_at DESC LIMIT ? OFFSET ?"
        params.extend([max(1, min(int(limit), 200)), max(0, int(offset))])
        with self.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self.fact_from_row(row) for row in rows]

    def search_facts(self, *, chat_key: str, query: str, limit: int = 8) -> list[FactRecord]:
        tokens = search_tokens(query)
        if not tokens:
            return []
        clauses = " OR ".join("(attribute LIKE ? OR value LIKE ? OR subject LIKE ?)" for _ in tokens[:8])
        params: list[Any] = [chat_key]
        for token in tokens[:8]:
            like = f"%{token}%"
            params.extend([like, like, like])
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM facts WHERE chat_key=? AND status='active' AND ({clauses}) "
                "ORDER BY confidence DESC, updated_at DESC LIMIT ?",
                (*params, max(1, min(int(limit), 50))),
            ).fetchall()
        return [self.fact_from_row(row) for row in rows]

    def count_facts(self, *, chat_key: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS c FROM facts WHERE chat_key=? AND status='active'", (chat_key,)
            ).fetchone()
        return int(row["c"] or 0)

    def delete_fact(self, *, chat_key: str, identifier: str | int) -> bool:
        with self.connect() as connection:
            row = self._resolve_row(connection, "facts", identifier)
            if row is None or row["chat_key"] != chat_key:
                return False
            connection.execute("DELETE FROM facts WHERE id=?", (row["id"],))
        return True

    @staticmethod
    def fact_from_row(row: sqlite3.Row) -> FactRecord:
        return FactRecord(
            id=row["id"], short_id=int(row["short_id"]), chat_key=row["chat_key"], user_id=row["user_id"],
            subject=row["subject"], attribute=row["attribute"], value=row["value"],
            confidence=float(row["confidence"]), source=row["source"], status=row["status"],
            created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
        )

    # -------------------------------------------------------------- 滚动摘要

    def add_digest(
        self,
        *,
        chat_key: str,
        window_start: int,
        window_end: int,
        summary: str,
        tags: Iterable[str] | None = None,
        now: float | None = None,
    ) -> DigestRecord:
        text = " ".join(str(summary or "").split())
        if not text:
            raise ValueError("Digest summary cannot be empty")
        timestamp = float(now or time.time())
        digest_id = uuid.uuid4().hex
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO digests(id,chat_key,window_start,window_end,summary,tags_json,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    digest_id, chat_key, int(window_start), int(window_end), text[:2000],
                    json.dumps(normalize_tags(tags), ensure_ascii=False), timestamp,
                ),
            )
            row = connection.execute("SELECT * FROM digests WHERE id=?", (digest_id,)).fetchone()
        return self.digest_from_row(row)

    def latest_digest(self, *, chat_key: str) -> DigestRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM digests WHERE chat_key=? ORDER BY window_end DESC, created_at DESC LIMIT 1",
                (chat_key,),
            ).fetchone()
        return self.digest_from_row(row) if row else None

    def list_digests(self, *, chat_key: str, limit: int = 5) -> list[DigestRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM digests WHERE chat_key=? ORDER BY window_end DESC LIMIT ?",
                (chat_key, max(1, min(int(limit), 50))),
            ).fetchall()
        return [self.digest_from_row(row) for row in rows]

    @staticmethod
    def digest_from_row(row: sqlite3.Row) -> DigestRecord:
        return DigestRecord(
            id=row["id"], chat_key=row["chat_key"], window_start=int(row["window_start"]),
            window_end=int(row["window_end"]), summary=row["summary"],
            tags=json.loads(row["tags_json"] or "[]"), created_at=float(row["created_at"]),
        )

    @staticmethod
    def memory_from_row(row: sqlite3.Row) -> MemoryRecord:
        keys = row.keys()
        return MemoryRecord(
            id=row["id"], short_id=int(row["short_id"]), chat_key=row["chat_key"], user_id=row["user_id"],
            memory_type=row["memory_type"], content=row["content"], summary=row["summary"],
            tags=json.loads(row["tags_json"] or "[]"), importance=float(row["importance"]),
            confidence=float(row["confidence"]), access_count=int(row["access_count"]), status=row["status"],
            source=row["source"], created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
            last_accessed_at=float(row["last_accessed_at"]),
            min_favor=int(row["min_favor"]) if "min_favor" in keys else 0,
        )
