"""好感度领域逻辑：事件驱动的分阶段状态机（FSM）。

设计原则（对应「别搞纯数值加减」）：
- 权威状态是「阶段」+「阶段内证据累积」，不是裸分数；
- 一切变化都由**关系事件**驱动，事件带类型、极性、严重度与具体证据；
- 阶段跃迁要同时满足三个条件：证据权重阈值、事件种类多样性、最短停留时间（滞后防抖）；
- 分数只是从 (阶段, 阶段内证据进度) **投影**出来的展示值，供排行榜与记忆门槛使用。

本模块只做纯计算，不碰数据库、不依赖 NekroAgent 框架，便于单独跑单测。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# --------------------------------------------------------------------- 阶段


@dataclass(frozen=True, slots=True)
class StageDef:
    """一个关系阶段的定义。"""

    name: str
    low: int  # 展示分下界（含）
    high: int  # 展示分上界（不含）；最高阶段 high 即上限
    guide: str  # 注入提示词的互动指导语
    up_threshold: float  # 升级所需的「净正向证据权重」
    down_threshold: float  # 降级所需的「净负向证据权重」
    min_hours: float  # 最短停留小时数（滞后，防抖）
    idle_demote_hours: float  # 多久无互动后自动回落一级；0 表示不自动回落


# 由低到高。索引即阶段等级 rank。
STAGES: tuple[StageDef, ...] = (
    StageDef(
        name="排斥",
        low=-100,
        high=-60,
        guide="保持距离，谨慎回应，必要时明确边界；不要主动示好。",
        up_threshold=6.0,
        down_threshold=0.0,
        min_hours=12.0,
        idle_demote_hours=0.0,
    ),
    StageDef(
        name="保留",
        low=-60,
        high=-20,
        guide="维持礼貌但克制，先观察，不要过度投入，也不要翻旧账。",
        up_threshold=4.0,
        down_threshold=3.0,
        min_hours=8.0,
        idle_demote_hours=720.0,
    ),
    StageDef(
        name="中立",
        low=-20,
        high=20,
        guide="正常友好互动，不主动施加亲密语气，也不冷淡。",
        up_threshold=4.0,
        down_threshold=3.0,
        min_hours=4.0,
        idle_demote_hours=1440.0,
    ),
    StageDef(
        name="亲近",
        low=20,
        high=60,
        guide="可以更自然、更积极地回应，适度体现熟悉感与默契。",
        up_threshold=8.0,
        down_threshold=4.0,
        min_hours=8.0,
        idle_demote_hours=2160.0,
    ),
    StageDef(
        name="偏爱",
        low=60,
        high=85,
        guide="可明显更热情，主动照顾对方体验并记住其偏好。",
        up_threshold=12.0,
        down_threshold=6.0,
        min_hours=12.0,
        idle_demote_hours=2880.0,
    ),
    StageDef(
        name="特别亲密",
        low=85,
        high=100,
        guide="可使用显著亲密与偏爱语气，但仍需遵守角色边界。",
        up_threshold=0.0,  # 最高阶段，无法再升级
        down_threshold=8.0,
        min_hours=24.0,
        idle_demote_hours=4320.0,
    ),
)

STAGE_NAMES: tuple[str, ...] = tuple(stage.name for stage in STAGES)
STAGE_INDEX: dict[str, int] = {stage.name: index for index, stage in enumerate(STAGES)}
DEFAULT_STAGE = "中立"

# min_favor 门槛 -> 需要的阶段（保持与旧版 0/20/60 语义一致）
UNLOCK_HINTS: tuple[tuple[int, str], ...] = ((0, "公开"), (20, "亲近"), (60, "偏爱"))
MIN_FAVOR_STAGE: tuple[tuple[int, str], ...] = ((60, "偏爱"), (20, "亲近"), (0, "排斥"))

STAGE_GUIDES: dict[str, str] = {stage.name: stage.guide for stage in STAGES}


def stage_def(stage: str) -> StageDef:
    return STAGES[STAGE_INDEX.get(str(stage), STAGE_INDEX[DEFAULT_STAGE])]


def stage_index(stage: str) -> int:
    return STAGE_INDEX.get(str(stage), STAGE_INDEX[DEFAULT_STAGE])


def stage_guide(stage: str) -> str:
    return stage_def(stage).guide


def clamp_stage(stage: str) -> str:
    return str(stage) if str(stage) in STAGE_INDEX else DEFAULT_STAGE


def unlock_hint(min_favor: int) -> str:
    """把 min_favor 门槛翻译成人话，用于注入提示。"""
    label = "公开"
    for threshold, name in UNLOCK_HINTS:
        if int(min_favor) >= threshold:
            label = name
    return label


def stage_for_min_favor(min_favor: int) -> str:
    """min_favor 门槛对应的最低阶段名。"""
    for threshold, name in MIN_FAVOR_STAGE:
        if int(min_favor) >= threshold:
            return name
    return DEFAULT_STAGE


def favor_unlocked(min_favor: int, stage: str) -> bool:
    """当前阶段是否已达到该记忆条目的门槛。"""
    return stage_index(stage) >= stage_index(stage_for_min_favor(min_favor))


def min_favor_ceiling_for_stage(stage: str) -> int:
    """当前阶段能解锁的最大 min_favor 门槛（用于 SQL 层预过滤，与 favor_unlocked 等价）。"""
    index = stage_index(stage)
    if index >= stage_index("偏爱"):
        return 10**6
    if index >= stage_index("亲近"):
        return 59
    return 19


# ------------------------------------------------------------- 关系事件类型


@dataclass(frozen=True, slots=True)
class EventKindDef:
    label: str
    polarity: int  # +1 正向 / -1 负向
    weight: float  # 基准证据权重
    hint: str  # 给 LLM 的判定说明


EVENT_KINDS: dict[str, EventKindDef] = {
    # ---- 正向
    "help": EventKindDef("主动帮忙", 1, 2.0, "主动且实质性地帮对方解决具体问题。"),
    "insight": EventKindDef("有价值的观点", 1, 1.5, "提供了对方认可的信息、思路或判断。"),
    "support": EventKindDef("情绪支持", 1, 2.0, "在对方低落时给予安抚、陪伴或共情。"),
    "shared_interest": EventKindDef("共同兴趣", 1, 1.0, "发现并投入地聊共同爱好、共同经历。"),
    "gift": EventKindDef("赠予分享", 1, 1.5, "分享资源、作品、礼物或机会给对方。"),
    "promise_kept": EventKindDef("守信", 1, 2.5, "之前答应的事被真正兑现。"),
    "deep_talk": EventKindDef("深入交流", 1, 2.0, "聊到私人话题、真实想法等较深层面。"),
    "banter": EventKindDef("有趣互动", 1, 0.8, "有来有回的玩笑、玩梗、调侃，气氛轻松。"),
    "reconcile": EventKindDef("和解", 1, 1.8, "冲突后主动缓和、道歉被接受或误会澄清。"),
    "loyalty": EventKindDef("维护站台", 1, 2.2, "在他人面前维护对方、替对方说话。"),
    # ---- 负向
    "disrespect": EventKindDef("冒犯贬低", -1, 2.0, "贬低、嘲讽、当众下对方面子。"),
    "promise_broken": EventKindDef("失信", -1, 3.0, "答应过的事没做到、放鸽子。"),
    "harassment": EventKindDef("骚扰越界", -1, 3.0, "反复纠缠、越界要求、无视拒绝。"),
    "betrayal": EventKindDef("背叛伤害", -1, 5.0, "泄露隐私、背后捅刀、实质性伤害。"),
    "spam": EventKindDef("刷屏滥用", -1, 1.0, "刷屏、滥用指令、把对话环境搞坏。"),
    "deception": EventKindDef("欺骗隐瞒", -1, 3.0, "被查实的说谎或刻意隐瞒。"),
    "neglect": EventKindDef("冷落无视", -1, 1.0, "长期无视对方的求助或示好。"),
    "boundary_push": EventKindDef("试探边界", -1, 1.5, "明知不可为仍反复试探底线。"),
}

SEVERITY_LABELS: dict[int, str] = {1: "轻微", 2: "明显", 3: "严重"}
SEVERITY_FACTOR: dict[int, float] = {1: 0.6, 2: 1.0, 3: 1.8}


def normalize_kind(kind: str) -> str:
    return str(kind or "").strip().lower()


def kind_polarity(kind: str) -> int:
    definition = EVENT_KINDS.get(normalize_kind(kind))
    return definition.polarity if definition else 0


def kind_label(kind: str) -> str:
    definition = EVENT_KINDS.get(normalize_kind(kind))
    return definition.label if definition else str(kind)


def kind_catalog() -> str:
    """给 LLM 的事件类型清单（注入工具描述用）。"""
    parts = []
    for kind, definition in EVENT_KINDS.items():
        parts.append(f"{kind}={definition.label}")
    return "、".join(parts)


# --------------------------------------------------------------- 证据与衰减


def evidence_decay(weight: float, hours: float, half_life_hours: float) -> float:
    """证据权重按半衰期衰减（对应「短期靠窗口、长期要沉淀」）。"""
    weight = float(weight)
    if weight <= 0 or hours <= 0:
        return weight
    half_life = max(1.0, float(half_life_hours))
    return weight * (0.5 ** (float(hours) / half_life))


@dataclass(slots=True)
class EventLimits:
    """一次事件记录的门槛与防刷分约束。"""

    max_severity: int = 3
    min_interval_minutes: int = 15
    max_events_per_day: int = 12
    max_positive_per_day: int = 8
    max_negative_per_day: int = 6
    max_evidence_chars: int = 200
    require_concrete_evidence: bool = True
    repeat_decay: float = 0.5  # 同一阶段内同类型事件重复出现时的边际递减


@dataclass(slots=True)
class EventOutcome:
    kind: str = ""
    polarity: int = 0
    weight: float = 0.0
    applied: bool = False
    rejected_reason: str = ""
    notes: list[str] = field(default_factory=list)


# 只有氛围、不含具体行为的词；证据去掉这些词后必须有剩余内容
ATMOSPHERE_WORDS: tuple[str, ...] = (
    "喜欢", "讨厌", "开心", "高兴", "难过", "生气", "感觉", "氛围", "不错", "很好",
    "不好", "可爱", "温柔", "有趣", "无聊", "谢谢", "感谢", "抱歉", "关系", "好感",
    "友好", "热情", "互动", "聊天", "发言", "表现",
)


def evidence_is_concrete(evidence: str) -> bool:
    """证据是否包含具体行为，而不是只有氛围词。

    先把「喜欢/不错/聊得」这类氛围词剔掉，剩下的部分还要够长才算「具体」。
    """
    text = "".join(str(evidence or "").split())
    if len(text) < 5:
        return False
    stripped = text
    for word in ATMOSPHERE_WORDS:
        stripped = stripped.replace(word, "")
    return len(stripped) >= 4


# 兼容旧名
def reason_is_concrete(reason: str) -> bool:
    return evidence_is_concrete(reason)


def event_weight(
    *,
    kind: str,
    severity: int,
    same_kind_count: int = 0,
    limits: EventLimits | None = None,
) -> float:
    """计算一次事件的证据权重（含严重度与同类型重复的边际递减）。"""
    rules = limits or EventLimits()
    definition = EVENT_KINDS.get(normalize_kind(kind))
    if definition is None:
        return 0.0
    severity = max(1, min(int(rules.max_severity), int(severity)))
    weight = definition.weight * SEVERITY_FACTOR.get(severity, 1.0)
    if same_kind_count > 0:
        weight = weight / (1.0 + float(rules.repeat_decay) * same_kind_count)
    return round(weight, 3)


def evaluate_event(
    *,
    kind: str,
    severity: int,
    evidence: str,
    stage: str,
    same_kind_count: int,
    events_today: int,
    positive_today: int,
    negative_today: int,
    last_event_at: float,
    now: float,
    limits: EventLimits,
) -> EventOutcome:
    """判定一次关系事件能否落库，并算出实际证据权重。"""
    key = normalize_kind(kind)
    definition = EVENT_KINDS.get(key)
    if definition is None:
        return EventOutcome(kind=key, rejected_reason=f"未知事件类型：{kind}；可用类型见工具说明。")

    text = " ".join(str(evidence or "").split())
    if limits.require_concrete_evidence and not evidence_is_concrete(text):
        return EventOutcome(
            kind=key,
            polarity=definition.polarity,
            rejected_reason="证据必须写明具体发生了什么，不能只有「聊得不错」这类氛围描述。",
        )
    if len(text) > limits.max_evidence_chars:
        text = text[: limits.max_evidence_chars]

    if limits.min_interval_minutes > 0 and last_event_at > 0:
        elapsed = now - float(last_event_at)
        window = limits.min_interval_minutes * 60.0
        if elapsed < window:
            wait = int(math.ceil((window - elapsed) / 60.0))
            return EventOutcome(
                kind=key,
                polarity=definition.polarity,
                rejected_reason=f"距上次关系事件不足 {limits.min_interval_minutes} 分钟，请约 {wait} 分钟后再记录。",
            )

    if events_today >= limits.max_events_per_day:
        return EventOutcome(
            kind=key,
            polarity=definition.polarity,
            rejected_reason=f"今日关系事件已达上限（{limits.max_events_per_day} 条）。",
        )
    if definition.polarity > 0 and positive_today >= limits.max_positive_per_day:
        return EventOutcome(
            kind=key,
            polarity=definition.polarity,
            rejected_reason=f"今日正向事件已达上限（{limits.max_positive_per_day} 条）。",
        )
    if definition.polarity < 0 and negative_today >= limits.max_negative_per_day:
        return EventOutcome(
            kind=key,
            polarity=definition.polarity,
            rejected_reason=f"今日负向事件已达上限（{limits.max_negative_per_day} 条）。",
        )

    notes: list[str] = []
    weight = event_weight(kind=key, severity=severity, same_kind_count=same_kind_count, limits=limits)
    if same_kind_count > 0:
        notes.append(f"本阶段内「{definition.label}」已出现 {same_kind_count} 次，触发边际递减")
    return EventOutcome(kind=key, polarity=definition.polarity, weight=weight, applied=True, notes=notes)


# ----------------------------------------------------------------- 状态跃迁


@dataclass(slots=True)
class TransitionRules:
    min_kinds: int = 2  # 升级至少需要多少种不同的正向事件
    max_step: int = 1  # 单次最多跨越几个阶段
    evidence_half_life_hours: float = 72.0


@dataclass(slots=True)
class StageDecision:
    stage: str
    direction: int = 0  # +1 升级 / -1 降级 / 0 不变
    reason: str = ""
    reset_evidence: bool = False
    carried: float = 0.0  # 跃迁后结转的富余权重


def decide_stage(
    *,
    stage: str,
    pos_weight: float,
    neg_weight: float,
    pos_kinds: int,
    entered_at: float,
    now: float,
    rules: TransitionRules,
    allow_idle_demote: bool = False,
    idle_hours: float = 0.0,
) -> StageDecision:
    """状态机核心：根据当前阶段内的证据，决定是否跃迁。

    跃迁三条件：净证据权重达阈值 + 事件种类足够 + 已在当前阶段停留够久（滞后）。
    """
    current = clamp_stage(stage)
    index = STAGE_INDEX[current]
    definition = STAGES[index]
    net = float(pos_weight) - float(neg_weight)
    elapsed_hours = max(0.0, (float(now) - float(entered_at)) / 3600.0)

    # 1) 升级：需要足够正向净证据 + 种类多样性 + 已过滞后
    if definition.up_threshold > 0 and net >= definition.up_threshold:
        if pos_kinds < max(1, int(rules.min_kinds)):
            return StageDecision(stage=current, reason="")
        if elapsed_hours < definition.min_hours:
            return StageDecision(stage=current, reason="")
        step = min(max(1, int(rules.max_step)), len(STAGES) - 1 - index)
        if step <= 0:
            return StageDecision(stage=current, reason="")
        target = STAGES[min(len(STAGES) - 1, index + step)]
        return StageDecision(
            stage=target.name,
            direction=1,
            reason=f"净正向证据 {net:.1f} ≥ {definition.up_threshold:.1f}，且出现 {pos_kinds} 类正向事件",
            reset_evidence=True,
            carried=max(0.0, net - definition.up_threshold),
        )

    # 2) 降级：需要足够负向净证据 + 已过滞后
    if definition.down_threshold > 0 and -net >= definition.down_threshold:
        if elapsed_hours < definition.min_hours:
            return StageDecision(stage=current, reason="")
        step = min(max(1, int(rules.max_step)), index)
        if step <= 0:
            return StageDecision(stage=current, reason="")
        target = STAGES[index - step]
        return StageDecision(
            stage=target.name,
            direction=-1,
            reason=f"净负向证据 {-net:.1f} ≥ {definition.down_threshold:.1f}",
            reset_evidence=True,
            carried=min(0.0, net + definition.down_threshold),
        )

    # 3) 长期无互动：自然回落一级（状态机式的「降温」，不是扣分数）
    if allow_idle_demote and definition.idle_demote_hours > 0 and index > 0:
        if float(idle_hours) >= definition.idle_demote_hours:
            target = STAGES[index - 1]
            return StageDecision(
                stage=target.name,
                direction=-1,
                reason=f"超过 {definition.idle_demote_hours / 24:.0f} 天无有效互动，关系自然回落",
                reset_evidence=True,
                carried=0.0,
            )

    return StageDecision(stage=current, reason="")


def project_score(
    *,
    stage: str,
    pos_weight: float,
    neg_weight: float,
    rules: TransitionRules | None = None,
) -> int:
    """把 (阶段, 阶段内证据) 投影成展示用的关系分。

    分数是**派生值**：排行榜排序、进度条、记忆门槛都读它，但它不是权威状态。
    """
    current = clamp_stage(stage)
    definition = stage_def(current)
    net = float(pos_weight) - float(neg_weight)
    if net >= 0:
        ceiling = definition.up_threshold or max(1.0, definition.high - definition.low)
        progress = net / (net + ceiling) if (net + ceiling) > 0 else 0.0
    else:
        floor = definition.down_threshold or max(1.0, definition.high - definition.low)
        progress = -((-net) / (-net + floor)) if (-net + floor) > 0 else 0.0
    ratio = max(0.0, min(1.0, 0.5 + 0.5 * progress))
    span = definition.high - definition.low
    return int(round(definition.low + span * ratio))


def score_to_stage(score: int) -> str:
    """展示分反查阶段（仅用于兼容旧数据/门槛语义）。"""
    value = int(score)
    for definition in STAGES:
        if value < definition.high:
            return definition.name
    return STAGES[-1].name


def format_delta(delta: int) -> str:
    return f"+{int(delta)}" if int(delta) >= 0 else str(int(delta))


def progress_ratio(score: int, max_abs: int) -> float:
    """排行榜进度条比例：只有正分才有条，按上限归一。"""
    max_abs = max(1, int(max_abs))
    return max(0.0, min(1.0, int(score) / max_abs))


def progress_ratio_by_stage(stage: str, pos_weight: float, neg_weight: float) -> float:
    """按状态机证据算进度条比例（供卡片用，比裸分数更贴近真实关系）。

    把「阶段等级 + 阶段内证据进度」摊平到 0..1，最低阶段为 0，最高阶段满格为 1。
    """
    current = clamp_stage(stage)
    index = STAGE_INDEX[current]
    definition = STAGES[index]
    net = float(pos_weight) - float(neg_weight)
    if definition.up_threshold > 0:
        inner = max(0.0, min(1.0, net / definition.up_threshold))
    else:
        inner = 1.0
    span = max(1, len(STAGES) - 1)
    return max(0.0, min(1.0, (index + inner) / span))


def direction_label(direction: int) -> str:
    if direction > 0:
        return "关系升温"
    if direction < 0:
        return "关系降温"
    return "关系持平"
