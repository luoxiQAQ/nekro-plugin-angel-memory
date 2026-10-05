from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from nekro_agent.services.user.deps import get_current_active_user, get_current_user
from nekro_agent.services.user.perm import Role, check_role, require_role

from .engine import engine, storage
from .favorability import stage_of
from .plugin import config, plugin

WEB_DIR = Path(__file__).parent / "web"


class MemoryUpdateBody(BaseModel):
    content: str | None = None
    summary: str | None = None
    tags: list[str] | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: str | None = None
    min_favor: int | None = Field(default=None, ge=0, le=10000)


class ImportBody(BaseModel):
    memories: list[dict[str, Any]]
    default_chat_key: str = ""


class FavorUpdateBody(BaseModel):
    chat_key: str
    user_id: str
    score: int | None = Field(default=None, ge=-10000, le=10000)
    delta: int | None = Field(default=None, ge=-10000, le=10000)
    summary: str | None = None
    interaction_hint: str | None = None
    tags: list[str] | None = None
    display_name: str | None = None
    reason: str = ""


async def _favor_access(request: Request, key: str = Query("", description="WebUI 访问密钥")) -> None:
    """好感度接口的访问控制：配置了 WEBUI_ACCESS_KEY 时可用 ?key= 免登录，否则回退 NA 管理员鉴权。"""
    expected = str(config.WEBUI_ACCESS_KEY or "").strip()
    if expected and str(key or "").strip() == expected:
        return
    try:
        user = await get_current_user(request)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=401,
            detail="未授权：请提供 NekroAgent 管理员令牌，或在配置里设置 WEBUI_ACCESS_KEY 后用 ?key= 访问。",
        ) from error
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号未激活")
    if not check_role(user, Role.Admin):
        raise HTTPException(status_code=403, detail="权限不足")


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

    @router.post("/reset")
    @require_role(Role.Admin)
    async def reset_data(
        chat_key: str = "",
        _current_user=Depends(get_current_active_user),
    ) -> dict[str, Any]:
        if chat_key.strip():
            return await asyncio.to_thread(storage.reset_channel, chat_key.strip())
        return await asyncio.to_thread(storage.reset_all)

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

    # ------------------------------------------------------------ 好感度

    @router.get("/favor")
    async def list_favors(
        chat_key: str,
        limit: int = 200,
        offset: int = 0,
        hide_empty: bool = False,
        _guard=Depends(_favor_access),
    ) -> dict[str, Any]:
        items = await asyncio.to_thread(
            storage.list_favors,
            chat_key=chat_key,
            limit=limit,
            offset=offset,
            hide_empty=hide_empty,
        )
        return {
            "items": [
                {**item.to_dict(), "stage": stage_of(item.score)} for item in items
            ],
            "max_abs_score": int(config.FAVOR_MAX_ABS_SCORE),
        }

    @router.get("/favor/events")
    async def list_favor_events(
        chat_key: str,
        user_id: str,
        limit: int = 10,
        _guard=Depends(_favor_access),
    ) -> dict[str, Any]:
        return {
            "items": await asyncio.to_thread(
                storage.list_favor_events,
                chat_key=chat_key,
                user_id=user_id,
                limit=limit,
            )
        }

    @router.post("/favor")
    async def upsert_favor(body: FavorUpdateBody, _guard=Depends(_favor_access)) -> dict[str, Any]:
        user_id = body.user_id.strip()
        if not user_id:
            raise HTTPException(status_code=422, detail="user_id 不能为空")
        if body.score is None and body.delta is None:
            raise HTTPException(status_code=422, detail="score 与 delta 至少要提供一个")
        if body.score is not None:
            profile = await asyncio.to_thread(
                storage.overwrite_favor,
                chat_key=body.chat_key,
                user_id=user_id,
                score=int(body.score),
                reason=body.reason or "WebUI 手动重设好感度",
                display_name=body.display_name or "",
                summary=body.summary or "",
                interaction_hint=body.interaction_hint or "",
                tags=body.tags,
                max_abs=int(config.FAVOR_MAX_ABS_SCORE),
                max_events=int(config.FAVOR_MAX_EVENT_HISTORY),
            )
        else:
            profile = await asyncio.to_thread(
                storage.apply_favor_delta,
                chat_key=body.chat_key,
                user_id=user_id,
                delta=int(body.delta or 0),
                reason=body.reason or "WebUI 手动调整好感度",
                display_name=body.display_name or "",
                summary=body.summary or "",
                interaction_hint=body.interaction_hint or "",
                tags=body.tags,
                max_abs=int(config.FAVOR_MAX_ABS_SCORE),
                max_events=int(config.FAVOR_MAX_EVENT_HISTORY),
            )
        return {**profile.to_dict(), "stage": stage_of(profile.score)}

    @router.delete("/favor")
    async def delete_favor(
        chat_key: str,
        user_id: str,
        _guard=Depends(_favor_access),
    ) -> dict[str, bool]:
        if not await asyncio.to_thread(storage.delete_favor, chat_key=chat_key, user_id=user_id):
            raise HTTPException(status_code=404, detail="好感度档案不存在")
        return {"ok": True}

    @router.post("/favor/decay")
    async def run_favor_decay(_guard=Depends(_favor_access)) -> dict[str, int]:
        return {"changed": await engine.run_favor_decay_if_due(force=True)}

    @router.post("/favor/recover")
    async def run_favor_recover(_guard=Depends(_favor_access)) -> dict[str, int]:
        return {"changed": await engine.run_favor_recover_if_due(force=True)}

    @router.get("/favor/card")
    async def favor_card(
        chat_key: str,
        limit: int = 20,
        _guard=Depends(_favor_access),
    ) -> FileResponse:
        from .main import build_rank_card

        profiles = await asyncio.to_thread(
            storage.list_favors,
            chat_key=chat_key,
            limit=limit,
            hide_empty=bool(config.FAVOR_RANK_HIDE_EMPTY),
        )
        if not profiles:
            raise HTTPException(status_code=404, detail="当前会话还没有建立任何好感度档案")
        path = await build_rank_card(chat_key, profiles)
        if path is None:
            raise HTTPException(status_code=500, detail="卡片渲染失败：请检查 Pillow 与中文字体")
        return FileResponse(str(path), media_type="image/png")

    @router.get("/ui", response_class=HTMLResponse)
    async def favor_ui() -> HTMLResponse:
        html = (WEB_DIR / "favor.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    return router
