"""T-059/T-062: NpcThinkParam aggression — T-062 起插值权重改由 adaptive lift 驱动。"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

from enemy_difficulty import (
    adaptive_stat_config,
    load_difficulty_cfg,
    resolve_slot_progression_tier,
)
from npc_think_sanitize import is_extreme_think, is_preserved_think, think_sanitize_config
from paths import GAME_DIR

INT_FIELDS = frozenset(
    {
        "eye_dist",
        "searchEye_dist",
        "nonBattleActLife",
        "maxBackhomeDist",
        "backhomeBattleDist",
        "goalAction_ToCaution",
        "goalAction_ToSearchLv1",
    }
)
# NpcThinkParam.xml 类型上限（写入 regulation 必须落在此范围）
U16_THINK_FIELDS = frozenset(
    {
        "eye_dist",
        "searchEye_dist",
        "nonBattleActLife",
        "maxBackhomeDist",
        "backhomeBattleDist",
    }
)
U8_THINK_FIELDS = frozenset(
    {
        "goalAction_ToCaution",
        "goalAction_ToSearchLv1",
    }
)
FLOAT_FIELDS = frozenset(
    {
        "SightTargetForgetTime",
        "MemoryTargetForgetTime",
        "SoundTargetForgetTime",
        "BackHomeLife_OnHitEneWal",
        "ear_dist",
        "nose_dist",
    }
)


def clamp_think_int_for_param(field: str, value: int) -> int:
    """Clamp think int overrides to PARAM cell type (u16/u8)."""
    v = int(value)
    if field in U8_THINK_FIELDS:
        return max(0, min(255, v))
    if field in U16_THINK_FIELDS:
        return max(0, min(65535, v))
    return v


def sanitize_think_field_overrides(overrides: dict[str, str]) -> dict[str, str]:
    """Drop/clamp overrides so NpcSoulPatch Coerce never OverflowException."""
    out: dict[str, str] = {}
    for key, raw in (overrides or {}).items():
        s = str(raw).strip()
        if not s:
            continue
        if key in FLOAT_FIELDS or "." in s:
            out[key] = s
            continue
        try:
            iv = int(s, 10)
        except ValueError:
            out[key] = s
            continue
        out[key] = str(clamp_think_int_for_param(key, iv))
    return out


def _ival_param(row: dict[str, str], field: str, default: int = 0) -> int:
    """Read int from think CSV row, clamped to PARAM type (CSV may show sentinels >u16)."""
    return clamp_think_int_for_param(field, _ival(row, field, default))


SANITIZE_CLAMP_KEYS = (
    "max_eye_dist",
    "max_search_eye_dist",
    "max_sight_forget_time",
    "max_backhome_dist",
    "max_backhome_battle_dist",
)

NIGHT_CLAMP_INT_FIELDS = frozenset(
    {
        "eye_dist",
        "searchEye_dist",
        "eye_angX",
        "eye_angY",
        "searchEye_angY",
        "backhomeDist",
        "maxBackhomeDist",
        "backhomeBattleDist",
        "BattleStartDist",
        "disableDark",
        "TeamAttackEffectivity",
        "callHelp_CallValidRange",
        "callHelp_CallValidMinDistTarget",
    }
)
NIGHT_CLAMP_FLOAT_FIELDS = frozenset(
    {
        "SightTargetForgetTime",
        "MemoryTargetForgetTime",
        # searchTargetLv1/Lv2ForgetTime：2026-09-08 真机=2 后红灵只看不打，已从 night clamp 撤出
        "SoundTargetForgetTime",
        "BackHomeLife_OnHitEneWal",
        "ear_dist",
        "nose_dist",
    }
)
# 红灵钳制：必须写成目标值（张角/开战距可抬高；禁只压低把视野拧成贴脸）
NIGHT_CLAMP_FORCE_SET_FIELDS = frozenset(
    {
        "nose_dist",
        "BattleStartDist",
        "disableDark",
        "eye_dist",
        "searchEye_dist",
        "eye_angX",
        "eye_angY",
        "searchEye_angY",
        "backhomeDist",
        "maxBackhomeDist",
        "backhomeBattleDist",
    }
)
# 兼容旧名
NIGHT_CLAMP_31000_FORCE_FIELDS = NIGHT_CLAMP_FORCE_SET_FIELDS
# 下限抬高（红灵基线常为 0，需抬到士兵档，不能走「只压低」）
NIGHT_CLAMP_FLOOR_FLOAT_FIELDS = frozenset(
    {
        "BackHomeLife_OnHitEneWal",
    }
)


def think_aggression_config(difficulty_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = load_difficulty_cfg() if difficulty_cfg is None else difficulty_cfg
    raw = dict(cfg.get("think_aggression") or {})
    defaults = {
        "enabled": True,
        "reference_tier": 9,
        "ai_scale_min": 0.15,
        "tier7_min_tier": 7,
    }
    out = {**defaults, **raw}
    out["enabled"] = bool(out.get("enabled", True))
    out["reference_tier"] = max(1, int(out.get("reference_tier", 9)))
    out["ai_scale_min"] = max(0.0, min(1.0, float(out.get("ai_scale_min", 0.15))))
    out["tier7_min_tier"] = int(out.get("tier7_min_tier", 7))
    return out


def ai_scale_for_slot_tier(
    slot_tier: int,
    aggression_cfg: dict[str, Any] | None = None,
) -> float:
    cfg = think_aggression_config(aggression_cfg)
    ref = int(cfg["reference_tier"])
    lo = float(cfg["ai_scale_min"])
    raw = max(0, int(slot_tier)) / ref
    return max(lo, min(1.0, raw))


def aggression_blend_t(ai_scale: float, aggression_cfg: dict[str, Any] | None = None) -> float:
    """Map ai_scale [min..1] → interpolation weight [0..1]."""
    cfg = think_aggression_config(aggression_cfg)
    lo = float(cfg["ai_scale_min"])
    if ai_scale <= lo:
        return 0.0
    if lo >= 1.0:
        return 1.0
    return (ai_scale - lo) / (1.0 - lo)


def sanitize_limits_for_tier(
    slot_tier: int,
    *,
    categories_cfg: dict[str, Any] | None = None,
    difficulty_cfg: dict[str, Any] | None = None,
) -> dict[str, float]:
    base = think_sanitize_config(categories_cfg)
    diff = load_difficulty_cfg() if difficulty_cfg is None else difficulty_cfg
    agg = think_aggression_config(diff)
    early = dict((diff.get("think_aggression") or {}).get("early_tier_sanitize") or {})
    tier7 = dict((diff.get("think_aggression") or {}).get("tier7_sanitize") or {})
    if int(slot_tier) >= int(agg["tier7_min_tier"]):
        base.update({k: v for k, v in tier7.items() if k in base or k.startswith("max_")})
    else:
        # Early/mid maps: tighter sense (Inquisitor eye=200 → early cap, not mid 35).
        base.update({k: v for k, v in early.items() if k in base or k.startswith("max_")})
    out: dict[str, float] = {}
    for key in SANITIZE_CLAMP_KEYS:
        try:
            out[key] = float(base.get(key, 0))
        except (TypeError, ValueError):
            out[key] = 0.0
    # nose/ear live outside SANITIZE_CLAMP_KEYS but extreme sanitize reads them.
    for key in ("max_nose_dist", "max_ear_dist"):
        try:
            out[key] = float(base.get(key, 0))
        except (TypeError, ValueError):
            out[key] = 0.0
    return out


@lru_cache(maxsize=4)
def _load_think_rows(csv_dir: str) -> dict[int, dict[str, str]]:
    path = Path(csv_dir) / "NpcThinkParam.csv"
    if not path.is_file():
        return {}
    rows: dict[int, dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                rows[int(row["ID"])] = row
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def _fval(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key) or default)
    except (TypeError, ValueError):
        return default


def _ival(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key) or default))
    except (TypeError, ValueError):
        return default


def _lerp_int(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def _lerp_float(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _night_clamp_targets(
    categories_cfg: dict[str, Any] | None,
    *,
    logic_id: str | int | None = None,
) -> dict[str, float]:
    del logic_id  # 现网不再按 logic 分档回家；保留参数免改调用方
    cfg = night_think_clamp_config(categories_cfg)
    return dict(cfg.get("targets") or {})


def _sanitize_limits_for_assignment(
    slot_tier: int,
    tgt_cat: str,
    *,
    categories_cfg: dict[str, Any] | None = None,
    difficulty_cfg: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Tier7 sanitize, but 5-pool night always uses night_think_clamp caps."""
    if str(tgt_cat or "") == "night":
        night = _night_clamp_targets(categories_cfg)
        sanitize = think_sanitize_config(categories_cfg)
        return {
            "max_eye_dist": float(night.get("eye_dist", 15)),
            "max_search_eye_dist": float(night.get("searchEye_dist", 7)),
            "max_sight_forget_time": float(
                night.get("SightTargetForgetTime", sanitize.get("max_sight_forget_time", 20))
            ),
            "max_backhome_dist": float(night.get("maxBackhomeDist", 45)),
            "max_backhome_battle_dist": float(night.get("backhomeBattleDist", 12)),
        }
    return sanitize_limits_for_tier(
        slot_tier,
        categories_cfg=categories_cfg,
        difficulty_cfg=difficulty_cfg,
    )


def _cap_target_int(
    field: str,
    target: int,
    limits: dict[str, float],
    *,
    night_targets: dict[str, float] | None = None,
) -> int:
    if night_targets and field in night_targets:
        target = min(target, int(night_targets[field]))
    if field == "eye_dist":
        cap = int(limits.get("max_eye_dist", target))
        return min(target, cap) if cap > 0 else target
    if field == "searchEye_dist":
        cap = int(limits.get("max_search_eye_dist", target))
        return min(target, cap) if cap > 0 else target
    if field in ("maxBackhomeDist",):
        cap = int(limits.get("max_backhome_dist", target))
        return min(target, cap) if cap > 0 else target
    if field in ("backhomeBattleDist",):
        cap = int(limits.get("max_backhome_battle_dist", target))
        return min(target, cap) if cap > 0 else target
    return target


def night_think_clamp_config(categories_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = (categories_cfg or {}).get("night_think_clamp") or {}
    default_targets = {
        # 5 池红灵：士兵档感知 + 压死 9999（见契约）
        "eye_dist": 40,
        "searchEye_dist": 20,
        "eye_angX": 60,
        "eye_angY": 45,
        "searchEye_angY": 20,
        "SightTargetForgetTime": 8.0,
        "MemoryTargetForgetTime": 10.0,
        "SoundTargetForgetTime": 3.0,
        "BackHomeLife_OnHitEneWal": 5.0,
        "backhomeDist": 50,
        "maxBackhomeDist": 70,
        "backhomeBattleDist": 20,
        "TeamAttackEffectivity": 35,
        "callHelp_CallValidRange": 0,
        "callHelp_CallValidMinDistTarget": 0,
        "ear_dist": 0.1,
        "nose_dist": 0.0,
        "BattleStartDist": 25,
        "disableDark": 0,
    }
    targets = dict(default_targets)
    targets.update({k: v for k, v in (raw.get("targets") or {}).items()})

    def _remap(key_new: str, key_old: str) -> int:
        raw_v = raw.get(key_new)
        if raw_v in (None, "", False):
            raw_v = raw.get(key_old)
        try:
            return int(raw_v) if raw_v not in (None, "", False) else 0
        except (TypeError, ValueError):
            return 0

    return {
        "enabled": bool(raw.get("enabled", True)),
        "targets": targets,
        "remap_logic_31000_to": _remap("remap_logic_31000_to", "trial_remap_logic_31000_to"),
        "remap_logic_30000_to": _remap("remap_logic_30000_to", "trial_remap_logic_30000_to"),
    }


def _effective_ival(
    row: dict[str, str],
    field: str,
    default: int,
    tgt_cat: str,
    categories_cfg: dict[str, Any] | None,
) -> int:
    base_v = _ival(row, field, default)
    if str(tgt_cat or "") != "night":
        return base_v
    cfg = night_think_clamp_config(categories_cfg)
    if not cfg.get("enabled", True):
        return base_v
    targets = cfg.get("targets") or {}
    if field in NIGHT_CLAMP_INT_FIELDS and field in targets:
        return min(base_v, int(targets[field]))
    return base_v


def _effective_fval(
    row: dict[str, str],
    field: str,
    default: float,
    tgt_cat: str,
    categories_cfg: dict[str, Any] | None,
) -> float:
    base_v = _fval(row, field, default)
    if str(tgt_cat or "") != "night":
        return base_v
    cfg = night_think_clamp_config(categories_cfg)
    if not cfg.get("enabled", True):
        return base_v
    targets = cfg.get("targets") or {}
    if field in NIGHT_CLAMP_FLOAT_FIELDS and field in targets:
        tgt = float(targets[field])
        if field in NIGHT_CLAMP_FLOOR_FLOAT_FIELDS:
            return max(base_v, tgt)
        return min(base_v, tgt)
    return base_v


def compute_think_extreme_sanitize_overrides(
    base_think: int,
    *,
    map_id: str = "",
    categories_cfg: dict[str, Any] | None = None,
    difficulty_cfg: dict[str, Any] | None = None,
    csv_dir: Path | str | None = None,
) -> dict[str, Any] | None:
    """Clamp extreme donor thinks to ``donor_think_sanitize`` caps (always).

    Patrol / early-map paths often keep raw donor think ids and skip aggression
    lerp when adaptive lift is 0 — that left ``eye_dist=200`` / ``nose=100`` /
    ``forget=9999`` (e.g. Inquisitor ``53111000``) on Limgrave slots. Contract:
    extreme sense must still become a 890M think copy.
    """
    if base_think <= 0:
        return None
    if is_preserved_think(base_think, categories_cfg):
        return None

    sanitize_cfg = think_sanitize_config(categories_cfg)
    if not sanitize_cfg.get("enabled", True):
        return None
    if not is_extreme_think(base_think, sanitize_cfg, csv_dir=csv_dir):
        return None

    base_dir = Path(csv_dir) if csv_dir else GAME_DIR / "csv"
    row = _load_think_rows(str(base_dir)).get(int(base_think))
    if not row:
        return None

    slot_tier = resolve_slot_progression_tier(map_id) if map_id else 1
    limits = sanitize_limits_for_tier(
        slot_tier,
        categories_cfg=categories_cfg,
        difficulty_cfg=difficulty_cfg,
    )
    overrides: dict[str, str] = {}

    int_caps = (
        ("eye_dist", "max_eye_dist"),
        ("searchEye_dist", "max_search_eye_dist"),
        ("maxBackhomeDist", "max_backhome_dist"),
        ("backhomeBattleDist", "max_backhome_battle_dist"),
    )
    for field, lim_key in int_caps:
        cap = float(limits.get(lim_key) or sanitize_cfg.get(lim_key) or 0)
        if cap <= 0:
            continue
        raw = _ival(row, field, 0)
        if raw > int(cap):
            overrides[field] = str(int(cap))

    float_caps = (
        ("ear_dist", "max_ear_dist"),
        ("nose_dist", "max_nose_dist"),
        ("SightTargetForgetTime", "max_sight_forget_time"),
        ("MemoryTargetForgetTime", "max_sight_forget_time"),
    )
    for field, lim_key in float_caps:
        cap = float(limits.get(lim_key) or sanitize_cfg.get(lim_key) or 0)
        if cap <= 0:
            continue
        raw = _fval(row, field, 0.0)
        if raw > cap + 0.001:
            overrides[field] = f"{cap:.4g}"

    if not overrides:
        return None

    agg = think_aggression_config(difficulty_cfg)
    ai_scale = ai_scale_for_slot_tier(slot_tier, agg)
    return {
        "base_think": int(base_think),
        "field_overrides": sanitize_think_field_overrides(overrides),
        "slot_tier": slot_tier,
        "ai_scale": round(ai_scale, 4),
        "adaptive_lift": 0.0,
        "extreme_sanitize_clamp": True,
    }


def compute_think_night_clamp_overrides(
    base_think: int,
    *,
    categories_cfg: dict[str, Any] | None = None,
    csv_dir: Path | str | None = None,
) -> dict[str, Any] | None:
    """Clamp 5-pool red spirit think vision/smell/chase/home to soldier-trash caps."""
    cfg = night_think_clamp_config(categories_cfg)
    if not cfg.get("enabled", True) or base_think <= 0:
        return None

    if is_preserved_think(base_think, categories_cfg):
        return None

    base_dir = Path(csv_dir) if csv_dir else GAME_DIR / "csv"
    row = _load_think_rows(str(base_dir)).get(int(base_think))
    if not row:
        return None

    logic_id = str(row.get("logicId") or "")
    remap_31000 = int(cfg.get("remap_logic_31000_to") or 0)
    remap_30000 = int(cfg.get("remap_logic_30000_to") or 0)
    # 产品：31000/30000 → 10000（去贴主机远冲）；钳制目标统一士兵档
    if remap_31000 and logic_id == "31000":
        clamp_logic_id = str(remap_31000)
    elif remap_30000 and logic_id == "30000":
        clamp_logic_id = str(remap_30000)
    else:
        clamp_logic_id = logic_id
    targets = _night_clamp_targets(categories_cfg, logic_id=clamp_logic_id)
    overrides: dict[str, str] = {}

    for field in NIGHT_CLAMP_INT_FIELDS:
        if field not in targets or field in NIGHT_CLAMP_FORCE_SET_FIELDS:
            continue
        base_v = _ival(row, field, 0)
        tgt = int(targets[field])
        if base_v <= tgt:
            continue
        overrides[field] = str(tgt)

    for field in NIGHT_CLAMP_FLOAT_FIELDS:
        if field not in targets or field in NIGHT_CLAMP_FORCE_SET_FIELDS:
            continue
        base_v = _fval(row, field, 0.0)
        tgt = float(targets[field])
        if field in NIGHT_CLAMP_FLOOR_FLOAT_FIELDS:
            if base_v + 0.001 >= tgt:
                continue
            overrides[field] = f"{tgt:.4g}"
            continue
        if base_v <= tgt + 0.001:
            continue
        overrides[field] = f"{tgt:.4g}"

    for field in NIGHT_CLAMP_FORCE_SET_FIELDS:
        if field not in targets:
            continue
        if field in NIGHT_CLAMP_FLOAT_FIELDS:
            overrides[field] = f"{float(targets[field]):.4g}"
        else:
            overrides[field] = str(int(targets[field]))

    if remap_31000 and logic_id == "31000":
        overrides["logicId"] = str(remap_31000)
    elif remap_30000 and logic_id == "30000":
        overrides["logicId"] = str(remap_30000)

    if not overrides:
        return None

    return {
        "base_think": int(base_think),
        "field_overrides": sanitize_think_field_overrides(overrides),
        "night_clamp": True,
        "slot_tier": 0,
        "ai_scale": 0.0,
    }


def think_anchor_targets(
    slot_tier: int,
    tgt_cat: str,
    *,
    difficulty_cfg: dict[str, Any] | None = None,
    categories_cfg: dict[str, Any] | None = None,
) -> dict[str, float]:
    """按 slot_tier 从 T-059 ``max_targets``（tier9）缩放出 Think 锚点。"""
    diff = load_difficulty_cfg() if difficulty_cfg is None else difficulty_cfg
    agg = think_aggression_config(diff)
    max_targets = dict((diff.get("think_aggression") or {}).get("max_targets") or {})
    ref = max(1, int(agg.get("reference_tier", 9)))
    s = max(float(agg.get("ai_scale_min", 0.15)), min(1.0, float(slot_tier) / float(ref)))
    anchors: dict[str, float] = {}

    for field, raw in max_targets.items():
        if field == "nonBattleActLife":
            # 高 tier 更主动（更小）；tier9 对齐 max_targets（通常 0）
            hi_idle = 4.0
            lo_idle = float(raw)
            anchors[field] = hi_idle + (lo_idle - hi_idle) * s
            continue
        if field in FLOAT_FIELDS:
            anchors[field] = float(raw) * s
        else:
            anchors[field] = float(raw) * s

    if str(tgt_cat or "") == "night":
        night = night_think_clamp_config(categories_cfg).get("targets") or {}
        for field in NIGHT_CLAMP_INT_FIELDS | NIGHT_CLAMP_FLOAT_FIELDS:
            if field in night and field in anchors:
                anchors[field] = min(float(anchors[field]), float(night[field]))
    return anchors


def compute_think_aggression_overrides(
    base_think: int,
    map_id: str,
    *,
    tgt_cat: str = "",
    categories_cfg: dict[str, Any] | None = None,
    difficulty_cfg: dict[str, Any] | None = None,
    csv_dir: Path | str | None = None,
    adaptive_lift: float | None = None,
    t093_stat_mult: float | None = None,
) -> dict[str, Any] | None:
    """Return field overrides for a think copy row, or None if no change.

    T-062：``adaptive_stat_anchor.enabled`` 时用 ``adaptive_lift`` 作插值权重；
    关闭时回退 T-059 ``ai_scale`` 权重。
    T-093：``t093_stat_mult`` 对视距/嗅觉/脱战等做乘法缩放（s=1 不变）。
    """
    from enemy_world_progression import t093_enabled

    diff = load_difficulty_cfg() if difficulty_cfg is None else difficulty_cfg
    agg_cfg = think_aggression_config(diff)
    if not agg_cfg.get("enabled", True) or base_think <= 0:
        return None

    if is_preserved_think(base_think, categories_cfg):
        return None

    slot_tier = resolve_slot_progression_tier(map_id)
    ai_scale = ai_scale_for_slot_tier(slot_tier, agg_cfg)
    adaptive_cfg = adaptive_stat_config(diff)

    if t093_enabled(diff):
        stat_m = float(t093_stat_mult if t093_stat_mult is not None else 1.0)
        if abs(stat_m - 1.0) < 1e-9 and str(tgt_cat or "") != "night":
            return None
        base_dir = Path(csv_dir) if csv_dir else GAME_DIR / "csv"
        row = _load_think_rows(str(base_dir)).get(int(base_think))
        if not row:
            return None
        limits = _sanitize_limits_for_assignment(
            slot_tier,
            tgt_cat,
            categories_cfg=categories_cfg,
            difficulty_cfg=diff,
        )
        night_targets = (
            _night_clamp_targets(categories_cfg, logic_id=row.get("logicId"))
            if str(tgt_cat or "") == "night"
            else None
        )
        night = str(tgt_cat or "") == "night"
        overrides: dict[str, str] = {}
        for field in (
            "eye_dist",
            "searchEye_dist",
            "eye_angX",
            "eye_angY",
            "searchEye_angY",
            "backhomeDist",
            "maxBackhomeDist",
            "backhomeBattleDist",
            "TeamAttackEffectivity",
            "callHelp_CallValidRange",
            "callHelp_CallValidMinDistTarget",
        ):
            raw_v = _ival(row, field, 0)
            if raw_v <= 0 and not night and field not in (
                "TeamAttackEffectivity",
                "callHelp_CallValidRange",
                "callHelp_CallValidMinDistTarget",
            ):
                continue
            out = max(0, int(round(raw_v * stat_m)))
            out = _cap_target_int(field, out, limits, night_targets=night_targets)
            if night and night_targets and field in night_targets:
                out = min(out, int(night_targets[field]))
            elif night and raw_v > 0:
                out = min(out, raw_v)
            if out != raw_v:
                overrides[field] = str(out)
        for field in ("ear_dist", "nose_dist"):
            raw_v = _fval(row, field, 0.0)
            if raw_v <= 0 and not night:
                continue
            out = max(0.0, raw_v * stat_m)
            if night and night_targets and field in night_targets:
                out = min(out, float(night_targets[field]), raw_v)
            if abs(out - raw_v) >= 0.001:
                overrides[field] = f"{out:.4g}"
        for field in ("SightTargetForgetTime", "MemoryTargetForgetTime"):
            raw_v = _fval(row, field, 0.0)
            if raw_v <= 0:
                continue
            out = max(0.0, raw_v * stat_m)
            if field == "SightTargetForgetTime":
                cap = float(limits.get("max_sight_forget_time", out) or out)
                out = min(out, cap)
            if abs(out - raw_v) >= 0.05:
                overrides[field] = f"{out:.4g}"
        if abs(stat_m - 1.0) > 1e-9:
            base_nbl = _ival_param(row, "nonBattleActLife", 1)
            if base_nbl > 0:
                out_nbl = max(0, int(round(base_nbl / stat_m)))
                out_nbl = clamp_think_int_for_param("nonBattleActLife", out_nbl)
                if out_nbl != base_nbl:
                    overrides["nonBattleActLife"] = str(out_nbl)
        if not overrides:
            return None
        return {
            "base_think": int(base_think),
            "field_overrides": sanitize_think_field_overrides(overrides),
            "slot_tier": slot_tier,
            "ai_scale": round(ai_scale, 4),
            "adaptive_lift": 0.0,
            "t093_stat_mult": round(stat_m, 6),
            "night_base_clamp": night,
        }

    use_lift = bool(adaptive_cfg.get("enabled", True))
    if use_lift:
        t = max(0.0, min(1.0, float(adaptive_lift or 0.0)))
    else:
        t = aggression_blend_t(ai_scale, agg_cfg)
    if t <= 0 and str(tgt_cat or "") != "night":
        return None

    base_dir = Path(csv_dir) if csv_dir else GAME_DIR / "csv"
    row = _load_think_rows(str(base_dir)).get(int(base_think))
    if not row:
        return None

    if use_lift:
        targets = think_anchor_targets(
            slot_tier,
            tgt_cat,
            difficulty_cfg=diff,
            categories_cfg=categories_cfg,
        )
    else:
        targets = {
            k: float(v)
            for k, v in dict((diff.get("think_aggression") or {}).get("max_targets") or {}).items()
        }
    limits = _sanitize_limits_for_assignment(
        slot_tier,
        tgt_cat,
        categories_cfg=categories_cfg,
        difficulty_cfg=diff,
    )
    night_targets = (
        _night_clamp_targets(categories_cfg, logic_id=row.get("logicId"))
        if str(tgt_cat or "") == "night"
        else None
    )

    overrides: dict[str, str] = {}
    night = str(tgt_cat or "") == "night"

    if "nonBattleActLife" in targets and t > 0:
        base_nbl = _ival_param(row, "nonBattleActLife", 1)
        tgt = max(0, int(round(float(targets["nonBattleActLife"]))))
        tgt = clamp_think_int_for_param("nonBattleActLife", tgt)
        out = _lerp_int(base_nbl, tgt, t)
        out = clamp_think_int_for_param("nonBattleActLife", out)
        if out != base_nbl:
            overrides["nonBattleActLife"] = str(out)

    for field in (
        "eye_dist",
        "searchEye_dist",
        "eye_angX",
        "eye_angY",
        "searchEye_angY",
        "backhomeDist",
        "maxBackhomeDist",
        "backhomeBattleDist",
        "TeamAttackEffectivity",
        "callHelp_CallValidRange",
        "callHelp_CallValidMinDistTarget",
    ):
        eff_v = _effective_ival(row, field, 0, tgt_cat, categories_cfg)
        raw_v = _ival(row, field, 0)
        if field in targets and t > 0:
            tgt = _cap_target_int(
                field,
                int(round(float(targets[field]))),
                limits,
                night_targets=night_targets,
            )
            out = _lerp_int(eff_v, tgt, t)
            out = _cap_target_int(field, out, limits, night_targets=night_targets)
            if night:
                out = min(out, eff_v)
            if out != raw_v:
                overrides[field] = str(out)
        elif night and eff_v != raw_v:
            overrides[field] = str(eff_v)

    for field in ("ear_dist", "nose_dist"):
        if not night:
            continue
        if field not in (night_targets or {}):
            continue
        raw_v = _fval(row, field, 0.0)
        tgt = float(night_targets[field])
        eff_v = min(raw_v, tgt)
        out = eff_v
        if field in targets and t > 0:
            anchor_tgt = min(float(targets[field]), tgt)
            out = _lerp_float(eff_v, anchor_tgt, t)
            out = min(out, eff_v)
        if abs(out - raw_v) >= 0.001:
            overrides[field] = f"{out:.4g}"

    for field in ("SightTargetForgetTime", "MemoryTargetForgetTime"):
        eff_v = _effective_fval(row, field, 0.0, tgt_cat, categories_cfg)
        raw_v = _fval(row, field, 0.0)
        if field in targets and t > 0:
            tgt = float(targets[field])
            if field == "SightTargetForgetTime":
                cap = limits.get("max_sight_forget_time", tgt)
                if cap > 0:
                    tgt = min(tgt, cap)
            out = _lerp_float(eff_v, tgt, t)
            if abs(out - raw_v) >= 0.05:
                overrides[field] = f"{out:.4g}"
        elif night and abs(eff_v - raw_v) >= 0.05:
            overrides[field] = f"{eff_v:.4g}"

    if t > 0:
        for field in ("goalAction_ToCaution", "goalAction_ToSearchLv1"):
            if field not in targets:
                continue
            base_v = _ival(row, field, 1)
            tgt = max(0, min(4, int(round(float(targets[field])))))
            out = _lerp_int(base_v, tgt, t)
            out = max(0, min(4, out))
            if out != base_v:
                overrides[field] = str(out)

    if not overrides:
        return None

    return {
        "base_think": int(base_think),
        "field_overrides": sanitize_think_field_overrides(overrides),
        "slot_tier": slot_tier,
        "ai_scale": round(ai_scale, 4),
        "adaptive_lift": round(t, 4) if use_lift else 0.0,
        "night_base_clamp": night,
    }


def think_patch_fingerprint(base_think: int, patch: dict[str, Any]) -> str:
    """Fingerprint for think-copy reuse.

    Includes ``slot_tier`` so late-map loose clamps (e.g. eye=80) cannot be
    reused on early-map slots (T-059 inquisitor-class leak).
    """
    parts = [str(base_think), f"tier={int(patch.get('slot_tier') or 0)}"]
    for key in sorted((patch.get("field_overrides") or {}).keys()):
        parts.append(f"{key}={patch['field_overrides'][key]}")
    return "|".join(parts)
