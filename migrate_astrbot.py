from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from .storage import AngelMemoryStorage


def attach_snapshot_tags(payload: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tag_names = {
        int(item["id"]): str(item["name"])
        for item in payload.get("global_tags", [])
        if isinstance(item, dict) and item.get("id") is not None and item.get("name")
    }
    tags_by_memory: dict[str, list[str]] = {}
    for relation in payload.get("memory_tag_rel", []):
        if not isinstance(relation, dict):
            continue
        try:
            memory_id = str(relation["memory_id"])
            tag_name = tag_names[int(relation["tag_id"])]
        except (KeyError, TypeError, ValueError):
            continue
        tags_by_memory.setdefault(memory_id, []).append(tag_name)
    enriched: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        if not item.get("tags"):
            item["tags"] = tags_by_memory.get(str(item.get("id") or ""), [])
        enriched.append(item)
    return enriched


def load_json_memories(source: Path) -> list[dict[str, Any]]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("content"), dict):
            payload = payload["content"]
        for key in ("memories", "records", "items", "data"):
            values = payload.get(key)
            if isinstance(values, list):
                records = [item for item in values if isinstance(item, dict)]
                return attach_snapshot_tags(payload, records) if key == "records" else records
    return []


def load_sqlite_memories(source: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(source)
    connection.row_factory = sqlite3.Row
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("memories", "memory_records", "memory"):
            if table in tables:
                records = [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
                if table != "memory_records" or not {"global_tags", "memory_tag_rel"}.issubset(tables):
                    return records
                payload = {
                    "global_tags": [dict(row) for row in connection.execute("SELECT id,name FROM global_tags")],
                    "memory_tag_rel": [
                        dict(row) for row in connection.execute("SELECT memory_id,tag_id FROM memory_tag_rel")
                    ],
                }
                return attach_snapshot_tags(payload, records)
    finally:
        connection.close()
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Import AstrBot Angel Memory data into the Nekro port")
    parser.add_argument("source", type=Path, help="Angel Memory JSON backup or SQLite database")
    parser.add_argument("target", type=Path, help="Target angel_memory.sqlite3 path")
    parser.add_argument("--chat-key", default="", help="Fallback Nekro chat_key when source has no scope")
    args = parser.parse_args()
    memories = load_json_memories(args.source) if args.source.suffix.lower() == ".json" else load_sqlite_memories(args.source)
    storage = AngelMemoryStorage(args.target)
    storage.initialize()
    print(json.dumps(storage.import_memories(memories, default_chat_key=args.chat_key), ensure_ascii=False))


if __name__ == "__main__":
    main()
