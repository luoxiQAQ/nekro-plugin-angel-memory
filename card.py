"""好感度排行榜卡片渲染（Pillow）。

缺 Pillow、缺中文字体或渲染异常时，统一返回 None，由调用方回退纯文本。
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, Iterable

from nekro_agent.core.logger import get_sub_logger

logger = get_sub_logger("angel_memory")

try:  # Pillow 是可选依赖，只影响排行榜卡片
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    PIL_AVAILABLE = True
except Exception:  # pragma: no cover - 环境缺 Pillow
    PIL_AVAILABLE = False

# ------------------------------------------------------------------ 版面常量

CARD_WIDTH = 1280
MARGIN = 32
COLUMN_GAP = 22
HEADER_HEIGHT = 140
ROW_HEIGHT = 82
ROW_GAP = 6
FOOTER_HEIGHT = 20

BG = (250, 245, 236)
CARD = (255, 255, 255)
CARD_BORDER = (241, 234, 224)
TOP_BG = (255, 247, 233)
TOP_BORDER = (246, 214, 170)
TEXT_MAIN = (60, 54, 50)
TEXT_SUB = (152, 145, 138)
RED = (233, 76, 76)
BAR_BG = (244, 236, 230)
TAG_BG = (253, 238, 234)
TAG_FG = (214, 104, 90)
BADGE_BG = (238, 232, 224)
BADGE_FG = (140, 133, 126)
BADGE_TOP = {1: (240, 176, 62), 2: (172, 180, 192), 3: (206, 148, 96)}

# 按优先级探测的中文字体；DejaVu 之类无中文字形的不列入
BOLD_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
)
REGULAR_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "C:/Windows/Fonts/msyh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
)

_FONT_SEARCH_DIRS = ("/usr/share/fonts", "C:/Windows/Fonts", "/System/Library/Fonts")
_FONT_SEARCH_PATTERN = re.compile(r"(notosanscjk|sourcehansans|wqy|msyh|pingfang|simhei|simsun)", re.I)


def _scan_font_dir(keyword: str) -> str | None:
    """在常见字体目录里兜底搜一遍。"""
    for directory in _FONT_SEARCH_DIRS:
        base = Path(directory)
        if not base.is_dir():
            continue
        try:
            for path in base.rglob("*"):
                if path.suffix.lower() not in (".ttc", ".ttf", ".otf"):
                    continue
                if _FONT_SEARCH_PATTERN.search(path.name):
                    if keyword == "bold" and "bold" not in path.name.lower():
                        continue
                    if keyword == "regular" and "bold" in path.name.lower():
                        continue
                    return str(path)
        except OSError:
            continue
    return None


def resolve_font(override: str, bold: bool) -> str | None:
    """返回可用的中文字体路径；找不到返回 None。"""
    candidates: Iterable[str] = (override,) if override else ()
    if not override:
        candidates = BOLD_FONT_CANDIDATES if bold else REGULAR_FONT_CANDIDATES
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return _scan_font_dir("bold" if bold else "regular")


class _FontBook:
    """按字号缓存字体对象；粗体缺字体时退回常规体。"""

    def __init__(self, override: str = "") -> None:
        self.bold_path = resolve_font(override, True)
        self.regular_path = resolve_font(override, False) or self.bold_path
        self._cache: dict[tuple[str, int], Any] = {}

    @property
    def available(self) -> bool:
        return bool(self.regular_path or self.bold_path)

    def get(self, size: int, bold: bool = False) -> Any:
        path = (self.bold_path if bold else self.regular_path) or self.regular_path or self.bold_path
        key = (str(path), int(size))
        font = self._cache.get(key)
        if font is None:
            font = ImageFont.truetype(str(path), int(size))
            self._cache[key] = font
        return font


# ------------------------------------------------------------------ 绘制工具


def _fit_text(draw: Any, text: str, font: Any, max_width: float) -> str:
    if max_width <= 0:
        return ""
    text = str(text or "")
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    while text and draw.textlength(text + ellipsis, font=font) > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ""


def _paste_avatar(canvas: Any, avatar_path: str | None, center: tuple[int, int], radius: int) -> bool:
    if not avatar_path or not os.path.exists(avatar_path):
        return False
    try:
        avatar = Image.open(avatar_path).convert("RGBA")
    except Exception:
        return False
    side = radius * 2
    try:
        avatar = ImageOps.fit(avatar, (side, side), Image.Resampling.LANCZOS)
    except Exception:
        return False
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, side - 1, side - 1), fill=255)
    canvas.paste(avatar, (center[0] - radius, center[1] - radius), mask)
    return True


def _initial_avatar(canvas: Any, draw: Any, name: str, center: tuple[int, int], radius: int, font: Any) -> None:
    palette = ((236, 178, 168), (176, 196, 224), (196, 214, 178), (226, 200, 166), (206, 186, 222))
    seed = sum(ord(char) for char in (name or "?")) or 1
    color = palette[seed % len(palette)]
    draw.ellipse(
        (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius),
        fill=color,
    )
    letter = (name or "?")[:1]
    draw.text(center, letter, font=font, fill=(255, 255, 255), anchor="mm")


def _draw_tag(draw: Any, x: float, y: float, text: str, font: Any, height: int = 26) -> float:
    text = str(text or "").strip()
    if not text:
        return x
    width = draw.textlength(text, font=font) + 16
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height / 2, fill=TAG_BG)
    draw.text((x + 8, y + height / 2), text, font=font, fill=TAG_FG, anchor="lm")
    return x + width + 6


# ------------------------------------------------------------------ 主渲染


def render_rank_card(
    entries: list[dict[str, Any]],
    out_path: Path,
    *,
    title: str = "好感度排行榜",
    max_abs: int = 100,
    font_override: str = "",
) -> Path | None:
    """把排行榜条目渲染成图片；任何异常都返回 None 交由上层回退文本。"""
    if not PIL_AVAILABLE:
        logger.warning("未安装 Pillow，好感度排行榜回退纯文本")
        return None
    if not entries:
        return None

    fonts = _FontBook(font_override)
    if not fonts.available:
        logger.warning("未找到可用的中文字体，好感度排行榜回退纯文本")
        return None

    try:
        columns = 2 if len(entries) > 1 else 1
        rows = (len(entries) + columns - 1) // columns
        body_height = rows * ROW_HEIGHT + max(0, rows - 1) * ROW_GAP
        height = HEADER_HEIGHT + body_height + FOOTER_HEIGHT + MARGIN
        column_width = (CARD_WIDTH - 2 * MARGIN - COLUMN_GAP * (columns - 1)) // columns

        canvas = Image.new("RGB", (CARD_WIDTH, height), BG)
        draw = ImageDraw.Draw(canvas)

        f_title = fonts.get(40, bold=True)
        f_badge = fonts.get(17, bold=True)
        f_name = fonts.get(22, bold=True)
        f_meta = fonts.get(15)
        f_tag = fonts.get(13)
        f_score = fonts.get(28, bold=True)
        f_stage = fonts.get(14)
        f_initial = fonts.get(24, bold=True)

        # 标题 + 左侧红条
        draw.rounded_rectangle((MARGIN + 4, 54, MARGIN + 12, 100), radius=4, fill=RED)
        draw.text((MARGIN + 28, 54), title, font=f_title, fill=TEXT_MAIN)

        for index, entry in enumerate(entries):
            column = index // rows
            row = index % rows
            x0 = MARGIN + column * (column_width + COLUMN_GAP)
            y0 = HEADER_HEIGHT + row * (ROW_HEIGHT + ROW_GAP)
            _draw_row(
                canvas,
                draw,
                x0=x0,
                y0=y0,
                width=column_width,
                entry=entry,
                rank=index + 1,
                max_abs=max_abs,
                fonts=fonts,
                f_badge=f_badge,
                f_name=f_name,
                f_meta=f_meta,
                f_tag=f_tag,
                f_score=f_score,
                f_stage=f_stage,
                f_initial=f_initial,
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(out_path, "PNG", optimize=True)
        return out_path
    except Exception:
        logger.exception("渲染好感度排行榜卡片失败")
        return None


def _draw_row(
    canvas: Any,
    draw: Any,
    *,
    x0: int,
    y0: int,
    width: int,
    entry: dict[str, Any],
    rank: int,
    max_abs: int,
    fonts: _FontBook,
    f_badge: Any,
    f_name: Any,
    f_meta: Any,
    f_tag: Any,
    f_score: Any,
    f_stage: Any,
    f_initial: Any,
) -> None:
    height = ROW_HEIGHT - ROW_GAP
    is_top = rank == 1
    draw.rounded_rectangle(
        (x0, y0, x0 + width, y0 + height),
        radius=16,
        fill=TOP_BG if is_top else CARD,
        outline=TOP_BORDER if is_top else CARD_BORDER,
        width=2 if is_top else 1,
    )

    center_y = y0 + height // 2

    # 名次徽章
    badge_center = (x0 + 34, center_y)
    badge_fill = BADGE_TOP.get(rank, BADGE_BG)
    badge_text = (255, 255, 255) if rank in BADGE_TOP else BADGE_FG
    draw.ellipse(
        (badge_center[0] - 18, badge_center[1] - 18, badge_center[0] + 18, badge_center[1] + 18),
        fill=badge_fill,
    )
    draw.text(badge_center, str(rank), font=f_badge, fill=badge_text, anchor="mm")

    # 头像
    name = str(entry.get("name") or entry.get("user_id") or "?")
    avatar_center = (x0 + 82, center_y)
    if not _paste_avatar(canvas, entry.get("avatar_path"), avatar_center, 25):
        _initial_avatar(canvas, draw, name, avatar_center, 25, f_initial)

    # 右侧分数 / 进度条 / 阶段
    right = x0 + width - 20
    score = int(entry.get("score") or 0)
    score_text = f"+{score}" if score >= 0 else str(score)
    draw.text((right, y0 + 8), score_text, font=f_score, fill=RED, anchor="ra")

    bar_width = 96
    bar_left = right - bar_width
    bar_top = y0 + 44
    draw.rounded_rectangle((bar_left, bar_top, right, bar_top + 6), radius=3, fill=BAR_BG)
    ratio = max(0.0, min(1.0, score / max(1, int(max_abs))))
    if ratio > 0:
        draw.rounded_rectangle(
            (bar_left, bar_top, bar_left + max(6, int(bar_width * ratio)), bar_top + 6),
            radius=3,
            fill=RED,
        )
    draw.text((right, y0 + 54), str(entry.get("stage") or ""), font=f_stage, fill=TEXT_SUB, anchor="ra")

    # 左侧文字区
    text_x = x0 + 116
    text_limit = bar_left - 14
    draw.text(
        (text_x, y0 + 10),
        _fit_text(draw, name, f_name, text_limit - text_x),
        font=f_name,
        fill=TEXT_MAIN,
    )

    meta = f"ID:{entry.get('user_id') or ''}"
    cursor = text_x + draw.textlength(meta + "  ", font=f_meta)
    draw.text((text_x, y0 + 42), meta, font=f_meta, fill=TEXT_SUB)

    for tag in list(entry.get("tags") or [])[:4]:
        tag_width = draw.textlength(str(tag), font=f_tag) + 20
        if cursor + tag_width > text_limit:
            break
        cursor = _draw_tag(draw, cursor, y0 + 39, str(tag), f_tag, height=22)


# ------------------------------------------------------------------ 头像下载

_AVATAR_URL = "http://q.qlogo.cn/g?b=qq&nk={user_id}&s=640"


async def fetch_avatars(
    user_ids: Iterable[str],
    cache_dir: Path,
    *,
    enabled: bool = True,
    timeout: float = 6.0,
) -> dict[str, str]:
    """尽力拉取 QQ 头像；失败或未启用时返回空字典（卡片会用首字占位）。"""
    result: dict[str, str] = {}
    if not enabled:
        return result
    try:
        import httpx
    except Exception:
        return result

    cache_dir.mkdir(parents=True, exist_ok=True)
    targets = []
    for user_id in user_ids:
        user_id = str(user_id or "").strip()
        if not user_id.isdigit():
            continue
        path = cache_dir / f"{user_id}.jpg"
        if path.exists() and path.stat().st_size > 0:
            result[user_id] = str(path)
        else:
            targets.append((user_id, path))
    if not targets:
        return result

    async def _one(client: Any, user_id: str, path: Path) -> None:
        try:
            response = await client.get(_AVATAR_URL.format(user_id=user_id))
            if response.status_code == 200 and response.content:
                await asyncio.to_thread(path.write_bytes, response.content)
                result[user_id] = str(path)
        except Exception:
            return

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            await asyncio.gather(*(_one(client, user_id, path) for user_id, path in targets))
    except Exception:
        logger.warning("拉取好感度排行榜头像失败，将使用首字占位")
    return result
