from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nekro_agent.services.user.deps import get_current_active_user
from nekro_agent.services.user.perm import Role, require_role

from .engine import engine, storage
from .plugin import config, plugin


class MemoryUpdateBody(BaseModel):
    content: str | None = None
    summary: str | None = None
    tags: list[str] | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: str | None = None


class ImportBody(BaseModel):
    memories: list[dict[str, Any]]
    default_chat_key: str = ""


@plugin.mount_router()
def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/status")
    @require_role(Role.Admin)
    async def status(_current_user=Depends(get_current_active_user)) -> dict[str, Any]:
        return {
            "ok": True,
            "database": str(storage.database_path),
            "fts_available": storage.get_state("fts_available", "1") == "1",
        }

    @router.get("/memories")
    @require_role(Role.Admin)
    async def list_memories(
        chat_key: str,
        status_filter: str = "active",
        limit: int = 100,
        offset: int = 0,
        _current_user=Depends(get_current_active_user),
    ) -> dict[str, Any]:
        items = await asyncio.to_thread(
            storage.list_memories,
            chat_key=chat_key,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
        return {"items": [item.to_dict() for item in items]}

    @router.patch("/memories/{memory_id}")
    @require_role(Role.Admin)
    async def update_memory(
        memory_id: str,
        body: MemoryUpdateBody,
        _current_user=Depends(get_current_active_user),
    ) -> dict[str, Any]:
        try:
            updated = await asyncio.to_thread(
                storage.update_memory,
                memory_id,
                **body.model_dump(exclude_none=True),
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if updated is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return updated.to_dict()

    @router.delete("/memories/{memory_id}")
    @require_role(Role.Admin)
    async def delete_memory(memory_id: str, _current_user=Depends(get_current_active_user)) -> dict[str, bool]:
        if not await asyncio.to_thread(storage.delete_memory, memory_id):
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"ok": True}

    @router.get("/notes")
    @require_role(Role.Admin)
    async def list_notes(
        chat_key: str,
        limit: int = 100,
        offset: int = 0,
        _current_user=Depends(get_current_active_user),
    ) -> dict[str, Any]:
        items = await asyncio.to_thread(storage.list_notes, chat_key=chat_key, limit=limit, offset=offset)
        return {"items": [item.to_dict() for item in items]}

    @router.delete("/notes/{note_id}")
    @require_role(Role.Admin)
    async def delete_note(note_id: str, _current_user=Depends(get_current_active_user)) -> dict[str, bool]:
        if not await asyncio.to_thread(storage.delete_note, note_id):
            raise HTTPException(status_code=404, detail="Note not found")
        return {"ok": True}

    @router.post("/consolidate")
    @require_role(Role.Admin)
    async def consolidate(chat_key: str, _current_user=Depends(get_current_active_user)) -> dict[str, int]:
        return await engine.consolidate(chat_key)

    @router.post("/maintenance")
    @require_role(Role.Admin)
    async def maintenance(_current_user=Depends(get_current_active_user)) -> dict[str, int]:
        result = await asyncio.to_thread(
            storage.maintenance,
            archive_after_days=config.ARCHIVE_AFTER_DAYS,
            archive_threshold=config.ARCHIVE_STRENGTH_THRESHOLD,
            max_memories_per_scope=config.MAX_MEMORIES_PER_SCOPE,
        )
        return result

    @router.get("/export")
    @require_role(Role.Admin)
    async def export_data(_current_user=Depends(get_current_active_user)) -> dict[str, Any]:
        return await asyncio.to_thread(storage.export_all)

    @router.post("/import")
    @require_role(Role.Admin)
    async def import_data(body: ImportBody, _current_user=Depends(get_current_active_user)) -> dict[str, int]:
        return await asyncio.to_thread(
            storage.import_memories,
            body.memories,
            default_chat_key=body.default_chat_key,
        )

    return router
