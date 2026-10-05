"""好感度领域逻辑：阶段换算、解锁门槛、防刷分约束、衰减/回升。

本模块只做纯计算，不碰数据库、不依赖 NekroAgent 框架，便于单独跑单测。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# --------------------------------------------------------------------- 阶段

STAGE_GUIDES: dict[str, str] = {
    "排斥": "保持距离，谨慎回应，必要时明确边界。",
    "保留": "维持礼貌但克制，先观察，不要过度投入。",
    "中立": "正常友好互动，不主动施加亲密语气。",
    "亲近": "可以更自然、更积极地回应，适度体现熟悉感。",
    "偏爱": "可明显更热情，主动照顾对方体验并记住其偏好。",
    "特别亲密": "可使用显著亲密与偏爱语气，但仍需遵守角色边界。",
}

# min_favor 的门槛语义（0=公开 / 20=亲近 / 60=偏爱）
UNLOCK_HINTS: tuple[tuple[int, str], ...] = ((0, "公开"), (20, "亲近"), (60, "偏爱"))


def stage_of(score: int) -> str:
    """把分数换算成阶段名（与参考实现保持同一套区间）。"""
    score = int(score)
    if score <= -60:
        return "排斥"
    if score <= -20:
        return "保留"
    if score < 20:
        return "中立"
    if score < 60:
        return "亲近"
    if score < 85:
        return "偏爱"
    return "特别亲密"


def stage_guide(score: int) -> str:
    return STAGE_GUIDES[stage_of(score)]


def unlock_hint(min_favor: int) -> str:
    """把 min_favor 门槛翻译成人话，用于注入提示。"""
    label = "公开"
    for threshold, name in UNLOCK_HINTS:
        if int(min_favor) >= threshold:
            label = name
    return label


def format_delta(delta: int) -> str:
    return f"+{int(delta)}" if int(delta) >= 0 else str(int(delta))


def progress_ratio(score: int, max_abs: int) -> float:
    """排行榜进度条比例：只有正分才有条，按上限归一。"""
    max_abs = max(1, int(max_abs))
    return max(0.0, min(1.0, int(score) / max_abs))


# --------------------------------------------------------------- 防刷分约束

# 只有氛围、不含具体行为的词；理由去掉这些词后必须有剩余内容
ATMOSPHERE_WORDS: tuple[str, ...] = (
    "喜欢", "讨厌", "开心", "高兴", "难过", "生气", "感觉", "氛围", "不错", "很好",
    "不好", "可爱", "温柔", "有趣", "无聊", "谢谢", "感谢", "抱歉", "关系", "好感",
    "友好", "热情", "互动", "聊天", "发言", "表现",
)


def reason_is_concrete(reason: str) -> bool:
    """理由是否包含具体行为，而不是只有氛围词。"""
    text = "".join(str(reason or "").split())
    if len(text) < 4:
        return False
    stripped = text
    for word in ATMOSPHERE_WORDS:
        stripped = stripped.replace(word, "")
    return len(stripped) >= 2


@dataclass(slots=True)
class AdjustLimits:
    max_abs: int = 100
    max_single: int = 10
    min_interval_minutes: int = 30
    max_daily_gain: int = 20
    max_daily_loss: int = 30
    require_concrete_reason: bool = True
    marginal_decay: bool = True


@dataclass(slots=True)
class AdjustOutcome:
    delta: int = 0
    applied: bool = False
    rejected_reason: str = ""
    notes: list[str] = field(default_factory=list)


def evaluate_adjustment(
    *,
    requested_delta: int,
    reason: str,
    score: int,
    last_adjust_at: float,
    today_gain: int,
    today_loss: int,
    now: float,
    limits: AdjustLimits,
) -> AdjustOutcome:
    """判定一次好感度调整是否放行，并按约束收敛实际分值。"""
    delta = int(requested_delta)
    if delta == 0:
        return AdjustOutcome(rejected_reason="delta 不能为 0；只改写档案描述请用「重设好感度档案」。")

    if limits.require_concrete_reason and not reason_is_concrete(reason):
        return AdjustOutcome(
            rejected_reason="理由必须写明具体行为，不能只有「喜欢/开心/不错」这类氛围词。"
        )

    if limits.min_interval_minutes > 0 and last_adjust_at > 0:
        elapsed = now - float(last_adjust_at)
        window = limits.min_interval_minutes * 60.0
        if elapsed < window:
            wait = int(math.ceil((window - elapsed) / 60.0))
            return AdjustOutcome(
                rejected_reason=f"距上次调整不足 {limits.min_interval_minutes} 分钟，请约 {wait} 分钟后再试。"
            )

    notes: list[str] = []
    capped = max(-limits.max_single, min(limits.max_single, delta))
    if capped != delta:
        notes.append(f"单次调整上限 ±{limits.max_single}，已收敛为 {format_delta(capped)}")
    delta = capped

    if limits.marginal_decay and delta > 0:
        factor = 1.0
        if score >= 85:
            factor = 0.3
        elif score >= 60:
            factor = 0.5
        if factor < 1.0:
            shrunk = max(1, int(round(delta * factor)))
            if shrunk != delta:
                notes.append("分数已较高，触发边际递减")
            delta = shrunk

    if delta > 0:
        room = int(limits.max_daily_gain) - int(today_gain)
        if room <= 0:
            return AdjustOutcome(rejected_reason=f"今日加分已达上限（{limits.max_daily_gain}）。")
        if delta > room:
            notes.append(f"今日加分上限 {limits.max_daily_gain}，已收敛为 {format_delta(room)}")
            delta = room
    elif delta < 0:
        room = int(limits.max_daily_loss) - int(today_loss)
        if room <= 0:
            return AdjustOutcome(rejected_reason=f"今日扣分已达上限（{limits.max_daily_loss}）。")
        if -delta > room:
            notes.append(f"今日扣分上限 {limits.max_daily_loss}，已收敛为 {format_delta(-room)}")
            delta = -room

    projected = int(score) + delta
    if projected > limits.max_abs:
        notes.append(f"已达好感度上限 {limits.max_abs}")
        delta = limits.max_abs - int(score)
    elif projected < -limits.max_abs:
        notes.append(f"已达好感度下限 {-limits.max_abs}")
        delta = -limits.max_abs - int(score)

    if delta == 0:
        return AdjustOutcome(rejected_reason="好感度已在边界，本次无需调整。")

    return AdjustOutcome(delta=delta, applied=True, notes=notes)


# ------------------------------------------------------------- 衰减与回升


def decay_delta(score: int, percent: int) -> int:
    """本次应扣减的分数（非负）。只有正分才衰减。"""
    score = int(score)
    percent = int(percent)
    if score <= 0 or percent <= 0:
        return 0
    return max(1, int(math.ceil(score * percent / 100.0)))


def recover_delta(score: int, percent: int) -> int:
    """本次应回升的分数（非负）。只有负分才回升，且不会越过 0。"""
    score = int(score)
    percent = int(percent)
    if score >= 0 or percent <= 0:
        return 0
    return max(1, int(math.ceil(abs(score) * percent / 100.0)))
