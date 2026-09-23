"""T-053: map-aligned difficulty patches for NpcParam copy rows (vanilla NG at runtime)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
DEFAULT_DIFFICULTY_PATH = SCRIPT_DIR / "enemy_difficulty.json"
DEFAULT_MAP_PROGRESSION_PATH = SCRIPT_DIR / "enemy_map_progression.json"

# SpEffect region / NG+ maxHpRate — synced to CNV Game/csv/SpEffectParam.csv (2026-08-08).
# Do not use vanished vanilla IDs (7170 / 7570 / 7580…); T8/T9 map to 7120 / 7520.
REGION_HP_MULT: dict[str, float] = {
    "7010": 3.340303,
    "7020": 3.985466,
    "7030": 4.630629,
    "7040": 5.275792,
    "7050": 5.920955,
    "7060": 6.566118,
    "7070": 7.211281,
    "7080": 7.856444,
    "7090": 8.501607,
    "7100": 9.14677,
    "7110": 9.791933,
    "7120": 10.4371,
    "7140": 8.2595,
    "7210": 5.307,
    "7220": 5.384,
    "7400": 2.0,
    "7410": 1.81,
    "7420": 1.68,
    "7430": 1.6,
    "7440": 1.5,
    "7450": 1.4,
    "7460": 1.3,
    "7470": 1.2,
    "7480": 1.18,
    "7490": 1.16,
    "7500": 1.14,
    "7510": 1.12,
    "7520": 1.1,
}

JOURNEY1_REGION_SP_MIN = 7010
JOURNEY1_REGION_SP_MAX = 7299
NG_REGION_SP_MIN = 7400
NG_REGION_SP_MAX = 7699

BOSS_SLOT_SRC_CATEGORIES = frozenset(
    {"minor_boss", "major_boss", "evergaol", "cnv_special"}
)

# 小 Boss / 场地 Boss：血量缩放只许加钱，不许压到阶梯以下（结晶人等表 hp 低但难打）
BOSS_RUNE_HP_BOOST_CATEGORIES = frozenset(
    {"minor_boss", "evergaol", "cnv_special"}
)

_DUNGEON_BOSS_ARENA_SLOT_RE = re.compile(r"^c\d{4}_9000$", re.IGNORECASE)
_DUNGEON_MAP_PREFIXES = ("m30_", "m31_", "m32_", "m35_")

SP_EFFECT_SLOT_PREFIX = "spEffectID"


def load_difficulty_cfg(path: Path | None = None) -> dict[str, Any]:
    return _load_difficulty_cfg_cached(str(path) if path else "")


@lru_cache(maxsize=4)
def _load_difficulty_cfg_cached(path_key: str) -> dict[str, Any]:
    path = Path(path_key) if path_key else DEFAULT_DIFFICULTY_PATH
    return json.loads(path.read_text(encoding="utf-8-sig"))


@lru_cache(maxsize=1)
def load_map_progression(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_MAP_PROGRESSION_PATH
    if not p.is_file():
        return {"by_map_id": {}, "default_tier": 5, "dungeon_default_tier": 4}
    return json.loads(p.read_text(encoding="utf-8-sig"))


def normalize_difficulty_settings(enemy_gui: dict[str, Any] | None) -> dict[str, Any]:
    from enemy_world_progression import t093_config, t093_enabled

    cfg = load_difficulty_cfg()
    defaults = dict(cfg.get("defaults") or {})
    raw = dict((enemy_gui or {}).get("difficulty") or {})
    out = {**defaults, **raw}
    out["enabled"] = bool(out.get("enabled", True))
    t093 = t093_config(cfg)
    try:
        lo = float(t093.get("user_mult_min", 0.85) if t093_enabled(cfg) else out.get("user_mult_min", 0.85))
        hi = float(t093.get("user_mult_max", 999.0) if t093_enabled(cfg) else out.get("user_mult_max", 999.0))
        user_mult = float(out.get("user_mult", 1.0))
        out["user_mult"] = max(lo, min(hi, user_mult))
    except (TypeError, ValueError):
        out["user_mult"] = 1.0
    try:
        default_base = 1.0 if t093_enabled(cfg) else 1.05
        out["baseline_over_vanilla"] = max(0.1, float(out.get("baseline_over_vanilla", default_base)))
    except (TypeError, ValueError):
        out["baseline_over_vanilla"] = 1.0 if t093_enabled(cfg) else 1.05
    return out


def sp_effect_ids(npc_row: dict[str, str]) -> list[str]:
    out: list[str] = []
    for key, val in npc_row.items():
        if not key.startswith(SP_EFFECT_SLOT_PREFIX):
            continue
        if val in ("", "-1", "0"):
            continue
        out.append(str(val))
    return out


def is_journey1_region_sp(sid: str) -> bool:
    try:
        n = int(sid)
    except (TypeError, ValueError):
        return False
    return JOURNEY1_REGION_SP_MIN <= n <= JOURNEY1_REGION_SP_MAX


def is_ng_region_sp(sid: str) -> bool:
    try:
        n = int(sid)
    except (TypeError, ValueError):
        return False
    return NG_REGION_SP_MIN <= n <= NG_REGION_SP_MAX


def region_hp_multiplier(npc_row: dict[str, str]) -> float:
    mult = 1.0
    for sid in sp_effect_ids(npc_row):
        tier = REGION_HP_MULT.get(sid)
        if tier is not None:
            mult = max(mult, tier)
    return mult


def _sp_effect_slot_index(key: str) -> int:
    try:
        return int(key.replace(SP_EFFECT_SLOT_PREFIX, ""))
    except ValueError:
        return 999


def npc_base_hp(npc_row: dict[str, str] | None) -> int:
    if not npc_row:
        return 0
    try:
        return int(npc_row.get("hp") or 0)
    except (TypeError, ValueError):
        return 0


def npc_base_def_flick(npc_row: dict[str, str] | None) -> int:
    if not npc_row:
        return 0
    try:
        return int(npc_row.get("defFlickPower") or 0)
    except (TypeError, ValueError):
        return 0


def effective_npc_hp(npc_row: dict[str, str]) -> int:
    base = npc_base_hp(npc_row)
    if base <= 0:
        return 0
    return max(1, round(base * region_hp_multiplier(npc_row)))


def resolve_slot_progression_tier(map_id: str, progression: dict[str, Any] | None = None) -> int:
    from enemy_world_progression import resolve_map_tier_t093, t093_enabled

    if t093_enabled():
        return resolve_map_tier_t093(map_id)
    progression = progression or load_map_progression()
    by_map = progression.get("by_map_id") or {}
    if map_id in by_map:
        return max(1, min(9, int(by_map[map_id])))
    map_s = str(map_id)
    dlc_prefix = str(progression.get("dlc_map_prefix") or "m61_")
    if dlc_prefix and map_s.startswith(dlc_prefix):
        return max(1, min(9, int(progression.get("dlc_default_tier", 9))))
    default_tier = int(progression.get("default_tier", 5))
    if map_s.startswith("m60_"):
        return default_tier
    return int(progression.get("dungeon_default_tier", 4))


def scale_rune_by_slot_tier(
    amount: int,
    map_id: str,
    *,
    progression: dict[str, Any] | None = None,
    difficulty_cfg: dict[str, Any] | None = None,
) -> int:
    """Scale kill runes by placement map tier; grows faster than HP (superlinear vs tier_stat)."""
    if amount <= 0:
        return 0
    progression = progression or load_map_progression()
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    slot_tier = resolve_slot_progression_tier(map_id, progression)
    baseline_tier = int(progression.get("default_tier", 5))
    slot_mult = tier_stat_multiplier(slot_tier, difficulty_cfg)
    base_mult = tier_stat_multiplier(baseline_tier, difficulty_cfg)
    if base_mult <= 0:
        return int(amount)
    diff_ratio = slot_mult / base_mult
    try:
        power = float(difficulty_cfg.get("rune_over_difficulty_power", 1.4))
    except (TypeError, ValueError):
        power = 1.4
    if power < 1.0:
        power = 1.0
    rune_ratio = diff_ratio**power if diff_ratio > 0 else 0.0
    return max(1, int(round(amount * rune_ratio)))


def tier_stat_multiplier(tier: int, difficulty_cfg: dict[str, Any] | None = None) -> float:
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    table = difficulty_cfg.get("tier_stat_multiplier") or {}
    return float(table.get(str(tier), table.get(str(max(1, min(9, tier))), 1.0)))


def region_sp_effect_ids(difficulty_cfg: dict[str, Any] | None = None) -> set[str]:
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    return {str(x) for x in (difficulty_cfg.get("region_sp_effect_ids") or REGION_HP_MULT)}


def ng_region_sp_effect_ids(difficulty_cfg: dict[str, Any] | None = None) -> set[str]:
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    return {str(x) for x in (difficulty_cfg.get("ng_region_sp_effect_ids") or [])}


def compute_map_align_scale(
    slot_tier: int,
    difficulty: dict[str, Any],
    difficulty_cfg: dict[str, Any] | None = None,
) -> float:
    """Mod hp/poise slider only; placement-map tier is applied via rebound spEffects."""
    from enemy_world_progression import t093_enabled

    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    if t093_enabled(difficulty_cfg):
        return 1.0
    _ = slot_tier
    baseline = float(difficulty.get("baseline_over_vanilla", 1.05))
    user_mult = float(difficulty.get("user_mult", 1.0))
    return baseline * user_mult


def _iter_sp_effect_slot_keys(npc_row: dict[str, str]) -> list[str]:
    return sorted(
        (k for k in npc_row if k.startswith(SP_EFFECT_SLOT_PREFIX)),
        key=_sp_effect_slot_index,
    )


def _first_empty_sp_slot(
    npc_row: dict[str, str],
    *,
    exclude: set[str] | None = None,
) -> str | None:
    skip = exclude or set()
    for key in _iter_sp_effect_slot_keys(npc_row):
        if key in skip:
            continue
        if str(npc_row.get(key) or "") in ("", "-1", "0"):
            return key
    return None


def _pick_ng_sp_slot(
    donor_row: dict[str, str],
    *,
    j1_primary: str,
) -> str:
    avoid = {j1_primary}
    empty = _first_empty_sp_slot(donor_row, exclude=avoid)
    if empty:
        return empty
    for key in _iter_sp_effect_slot_keys(donor_row):
        if key not in avoid:
            return key
    return "spEffectID2" if j1_primary != "spEffectID2" else "spEffectID3"


GAME_CLEAR_SP_EFFECT_KEY = "GameClearSpEffectID"


def _iter_hp_scaled_sp_keys(donor_row: dict[str, str]) -> list[str]:
    """spEffectID* + GameClearSpEffectID (donor leftover HP mults may sit on either)."""
    keys = list(_iter_sp_effect_slot_keys(donor_row))
    if GAME_CLEAR_SP_EFFECT_KEY in donor_row:
        keys.append(GAME_CLEAR_SP_EFFECT_KEY)
    elif GAME_CLEAR_SP_EFFECT_KEY not in keys:
        keys.append(GAME_CLEAR_SP_EFFECT_KEY)
    return keys


def _zero_leftover_hp_rate_sps(
    donor_row: dict[str, str],
    overrides: dict[str, str],
) -> None:
    """Clear any SpEffect/GameClear whose maxHpRate≠1 (T-093 表血已含；禁皮自带再乘).

    Call *before* writing the intentional NG (and optional J1) region ids so those
    writes win. Pure attack packs (maxHpRate==1) are left alone.
    """
    for key in _iter_hp_scaled_sp_keys(donor_row):
        val = donor_row.get(key, "")
        if val in ("", "-1", "0", None):
            continue
        try:
            sid = int(val)
        except (TypeError, ValueError):
            continue
        if sid <= 0:
            continue
        if is_journey1_region_sp(sid) or is_ng_region_sp(sid) or _attack_sp_has_hp_mult(sid):
            overrides[key] = "0"


# 人型红灵（c0000）：地图/周目血靠 Human-NPC Area / NG+ Scaling，不能清掉只写表血。
HUMAN_NPC_HP_MODEL_PREFIXES: tuple[str, ...] = ("c0000",)

# SOTE Human-NPC Area + NG+（同档 +400）
_DLC_HUMAN_NPC_AREA_NG: dict[str, tuple[int, int]] = {
    "dlc_gravesite": (20007200, 20007600),
    "dlc_altus": (20007240, 20007640),
    "dlc_south": (20007230, 20007630),
    "dlc_rauh": (20007290, 20007690),
    "dlc_abyss": (20007300, 20007700),
}


def is_human_npc_hp_model(model: str) -> bool:
    m = str(model or "").lower()
    return any(m.startswith(p) for p in HUMAN_NPC_HP_MODEL_PREFIXES)


def is_human_npc_area_sp(sid: int) -> bool:
    return (19351 <= sid <= 19371) or (20007200 <= sid <= 20007350)


def is_human_npc_ng_sp(sid: int) -> bool:
    return (19500 <= sid <= 19517) or (20007600 <= sid <= 20007750)


def resolve_human_npc_area_ng_sp(map_id: str) -> tuple[int, int]:
    """落点图 → 人型区域加成 + 人型周目加成（与法魂原皮同通道）。"""
    from enemy_world_progression import resolve_map_region_id, resolve_map_tier_t093

    region_id, _ = resolve_map_region_id(map_id)
    if region_id in _DLC_HUMAN_NPC_AREA_NG:
        return _DLC_HUMAN_NPC_AREA_NG[region_id]
    tier = resolve_map_tier_t093(map_id)
    idx = max(0, min(19, int(tier) - 1))
    area = 19351 + idx
    ng = min(19517, area + 150)
    return area, ng


def resolve_human_npc_table_hp(
    donor_row: dict[str, str],
    difficulty: dict[str, Any],
) -> int:
    """人型红灵表血：原皮底 × 滑条（区域/周目由引擎乘 Human-NPC sp）。"""
    base = npc_base_hp(donor_row)
    if base <= 0:
        return 0
    try:
        user_mult = float(difficulty.get("user_mult", 1.0))
    except (TypeError, ValueError):
        user_mult = 1.0
    return max(1, int(round(base * user_mult)))


def rebind_human_npc_sp_effects(
    donor_row: dict[str, str],
    map_id: str,
    difficulty_cfg: dict[str, Any] | None = None,
) -> dict[str, str]:
    """清残留血倍后，按落点重绑人型区域 + GameClear 人型周目（不写怪物 74xx）。"""
    _ = difficulty_cfg
    overrides: dict[str, str] = {}
    _zero_leftover_hp_rate_sps(donor_row, overrides)
    area, ng = resolve_human_npc_area_ng_sp(map_id)
    area_slot = "spEffectID3"
    for key, val in donor_row.items():
        if not key.startswith(SP_EFFECT_SLOT_PREFIX):
            continue
        if val in ("", "-1", "0", None):
            continue
        try:
            sid = int(val)
        except (TypeError, ValueError):
            continue
        if is_human_npc_area_sp(sid):
            area_slot = key
            break
    overrides[area_slot] = str(int(area))
    overrides[GAME_CLEAR_SP_EFFECT_KEY] = str(int(ng))
    return overrides


def rebind_region_sp_effects(
    donor_row: dict[str, str],
    slot_tier: int,
    difficulty_cfg: dict[str, Any] | None = None,
    *,
    map_id: str = "",
    model: str = "",
) -> dict[str, str]:
    """Rebind Journey-1 and NG+ region spEffects to the slot map tier.

    Always writes **one** NG+ id (7410~7580) so vanilla NG cycle scaling can apply.
    When ``clear_j1_region_sp``: clear J1 region ids (表血已含). Also clears any
    leftover SpEffect/GameClear with maxHpRate≠1 (DLC/area packs like 20007xxx).

    人型红灵（c0000）：改走 Human-NPC 区域/周目通道（2026-09-23）。
    """
    from enemy_world_progression import t093_config, t093_enabled

    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    if is_human_npc_hp_model(model) and map_id:
        return rebind_human_npc_sp_effects(donor_row, map_id, difficulty_cfg)
    if t093_enabled(difficulty_cfg) and t093_config(difficulty_cfg).get("clear_j1_region_sp"):
        overrides: dict[str, str] = {}
        _zero_leftover_hp_rate_sps(donor_row, overrides)
        target_ng = tier_to_ng_region_sp_effect(slot_tier, difficulty_cfg)
        ng_primary = _pick_ng_sp_slot(donor_row, j1_primary="spEffectID1")
        overrides[ng_primary] = str(int(target_ng))
        return overrides
    target_j1 = tier_to_region_sp_effect(slot_tier, difficulty_cfg)
    target_ng = tier_to_ng_region_sp_effect(slot_tier, difficulty_cfg)
    j1_slots: list[str] = []
    ng_slots: list[str] = []
    for key, val in donor_row.items():
        if not key.startswith(SP_EFFECT_SLOT_PREFIX):
            continue
        if val in ("", "-1", "0"):
            continue
        if is_ng_region_sp(val):
            ng_slots.append(key)
        elif is_journey1_region_sp(val):
            j1_slots.append(key)

    overrides: dict[str, str] = {}
    _zero_leftover_hp_rate_sps(donor_row, overrides)

    if j1_slots:
        j1_primary = min(j1_slots, key=_sp_effect_slot_index)
        overrides[j1_primary] = str(int(target_j1))
        for key in j1_slots:
            if key != j1_primary:
                overrides[key] = "0"
    else:
        j1_primary = _first_empty_sp_slot(donor_row) or "spEffectID1"
        overrides[j1_primary] = str(int(target_j1))

    if ng_slots:
        ng_primary = min(ng_slots, key=_sp_effect_slot_index)
        if ng_primary == j1_primary:
            ng_primary = _pick_ng_sp_slot(donor_row, j1_primary=j1_primary)
        overrides[ng_primary] = str(int(target_ng))
        for key in ng_slots:
            if key != ng_primary:
                overrides[key] = "0"
    else:
        ng_primary = _pick_ng_sp_slot(donor_row, j1_primary=j1_primary)
        overrides[ng_primary] = str(int(target_ng))

    return overrides


def scale_int(base: int, mult: float) -> int:
    if base <= 0:
        return base
    return max(1, int(math.ceil(base * mult)))


def floor_base_hp_for_donor(
    donor_row: dict[str, str],
    floor_effective: int,
) -> int | None:
    if floor_effective <= 0:
        return None
    base = npc_base_hp(donor_row)
    if base <= 0:
        return floor_effective
    mult = region_hp_multiplier(donor_row)
    needed = math.ceil(floor_effective / mult) if mult > 0 else floor_effective
    if needed <= base:
        return None
    return needed


def boss_slot_hp_floor(
    *,
    src_cat: str,
    src_npc: int,
    donor_npc: int,
    map_id: str,
    npc_by_id: dict[int, dict[str, str]],
    difficulty_cfg: dict[str, Any] | None = None,
) -> int | None:
    if src_cat not in BOSS_SLOT_SRC_CATEGORIES:
        return None
    if src_npc <= 0 or donor_npc <= 0 or src_npc == donor_npc:
        return None
    slot_row = npc_by_id.get(src_npc)
    donor_row = npc_by_id.get(donor_npc)
    if slot_row is None or donor_row is None:
        return None
    slot_eff = effective_npc_hp(slot_row)
    slot_tier = resolve_slot_progression_tier(map_id)
    slot_mult = tier_stat_multiplier(slot_tier, difficulty_cfg)
    donor_base = npc_base_hp(donor_row)
    donor_eff = donor_base * slot_mult if slot_mult > 0 else donor_base
    if donor_eff >= slot_eff:
        return None
    needed = math.ceil(slot_eff / slot_mult) if slot_mult > 0 else slot_eff
    if needed <= donor_base:
        return None
    return needed


def dungeon_boss_arena_min_base_hp(
    row: dict[str, Any],
    difficulty_cfg: dict[str, Any] | None = None,
) -> int | None:
    """洞窟/墓地 ``_9000`` Boss 战点：捐皮 base hp 不得低于配置（防墓影/调香师皮 <1000）。"""
    if str(row.get("src_cat") or "") != "minor_boss":
        return None
    if str(row.get("tgt_cat") or "") != "minor_boss":
        return None
    map_id = str(row.get("map_id") or "").lower()
    if not any(map_id.startswith(p) for p in _DUNGEON_MAP_PREFIXES):
        return None
    if not _DUNGEON_BOSS_ARENA_SLOT_RE.match(str(row.get("entity_name") or "")):
        return None
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    try:
        min_hp = int(difficulty_cfg.get("dungeon_boss_arena_min_base_hp") or 0)
    except (TypeError, ValueError):
        min_hp = 0
    return min_hp if min_hp > 0 else None


def region_hp_multiplier_for_slot_tier(
    slot_tier: int,
    difficulty_cfg: dict[str, Any] | None = None,
    *,
    map_id: str = "",
) -> float:
    """Journey-1 engine region maxHpRate. T-093：表血已含 map_mult，J1 区域 sp 已清 → 恒 1.0。"""
    from enemy_world_progression import t093_enabled

    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    if t093_enabled(difficulty_cfg):
        _ = (slot_tier, map_id)
        return 1.0
    sp_id = tier_to_region_sp_effect(slot_tier, difficulty_cfg)
    return float(REGION_HP_MULT.get(sp_id, 1.0))


def resolve_t093_target_effective_hp(
    row: dict[str, Any],
    donor_row: dict[str, str],
    *,
    difficulty: dict[str, Any],
    npc_by_id: dict[int, dict[str, str]],
    difficulty_cfg: dict[str, Any] | None = None,
) -> int:
    """白名单 → 夜 → 周目层lift → 硬帽（层前血）→ 滑条×地图分算相乘（T-099 D）。

    2026-09-23：地图层对「层前血」算，不再吃滑条压后血（防 0.25 反超 0.5）。
    """
    from enemy_whitelist_hp import resolve_donor_baseline_effective_hp
    from enemy_world_progression import (
        asymmetric_layer_lift_mult,
        compute_slider_lift_mult,
        map_layer_lift_mult,
        night_mult_for_row,
        nominal_journey_hp_mult,
        nominal_map_hp_mult,
        resolve_bracket_cap_mult,
        resolve_journey_tier,
        resolve_map_mult_t093,
        resolve_map_tier_t093,
        t093_config,
        t094_config,
        t094_enabled,
    )

    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    t093 = t093_config(difficulty_cfg)
    map_id = str(row.get("map_id") or "")
    base = resolve_donor_baseline_effective_hp(row, donor_row, npc_by_id=npc_by_id)
    if base <= 0:
        return 0

    h_ref = float(t093.get("lift_h_ref", 2500.0))
    alpha = float(t093.get("lift_alpha", 0.5))
    h = float(base)
    map_nom = 1.0
    use_t094 = t094_enabled(difficulty_cfg)

    night_m = night_mult_for_row(row, map_id, difficulty_cfg=difficulty_cfg)
    h *= night_m

    if use_t094:
        t094 = t094_config(difficulty_cfg)
        h_ref_l = float(t094.get("layer_lift_h_ref", h_ref))
        alpha_l = float(t094.get("layer_lift_alpha", alpha))
        map_tier = resolve_map_tier_t093(map_id)
        map_nom = nominal_map_hp_mult(map_tier, difficulty_cfg=difficulty_cfg)
        journey_tier = resolve_journey_tier(difficulty)
        j_nom = nominal_journey_hp_mult(journey_tier, difficulty_cfg=difficulty_cfg)
        j_eff = asymmetric_layer_lift_mult(h, j_nom, h_ref=h_ref_l, alpha=alpha_l)
        h *= j_eff
        cap = float(base) * resolve_bracket_cap_mult(
            base, kind="hp", difficulty_cfg=difficulty_cfg
        )
        h = min(h, cap)
    else:
        map_nom = float(resolve_map_mult_t093(map_id))

    # T-099 D：滑条与地图均对层前血分算，再相乘（互不喂对方结果）
    h_pre = h
    user_mult = float(difficulty.get("user_mult", 1.0))
    lift_m = compute_slider_lift_mult(
        h_pre,
        user_mult,
        h_ref=float(t093.get("lift_h_ref", 2500.0)),
        alpha=float(t093.get("lift_alpha", 0.5)),
    )
    if use_t094:
        map_eff = map_layer_lift_mult(h_pre, map_nom, difficulty_cfg=difficulty_cfg)
    else:
        map_eff = float(map_nom)
    h = h_pre * lift_m * map_eff

    return max(1, int(round(h)))


def resolve_t093_assignment_hp_out(
    row: dict[str, Any],
    donor_row: dict[str, str],
    *,
    difficulty: dict[str, Any],
    npc_by_id: dict[int, dict[str, str]],
    difficulty_cfg: dict[str, Any] | None = None,
) -> int:
    """表 hp：已含 map/夜/滑条；J1 区域 sp 清零，不再反除倍率。"""
    target_eff = resolve_t093_target_effective_hp(
        row,
        donor_row,
        difficulty=difficulty,
        npc_by_id=npc_by_id,
        difficulty_cfg=difficulty_cfg,
    )
    if target_eff <= 0:
        return 0
    map_id = str(row.get("map_id") or "")
    hp_out = max(1, int(target_eff))
    boss_floor = boss_slot_hp_floor(
        src_cat=str(row.get("src_cat") or ""),
        src_npc=int(row.get("src_npc") or 0),
        donor_npc=int(row.get("npc") or 0),
        map_id=map_id,
        npc_by_id=npc_by_id,
        difficulty_cfg=difficulty_cfg,
    )
    if boss_floor is not None and boss_floor > hp_out:
        hp_out = boss_floor
    arena_min = dungeon_boss_arena_min_base_hp(row, difficulty_cfg)
    if arena_min is not None and arena_min > hp_out:
        hp_out = arena_min
    return hp_out


def resolve_assignment_hp_out(
    row: dict[str, Any],
    donor_row: dict[str, str],
    *,
    difficulty: dict[str, Any],
    npc_by_id: dict[int, dict[str, str]],
    difficulty_cfg: dict[str, Any] | None = None,
) -> int:
    """Patched NpcParam ``hp`` table value (before in-game region sp multipliers)."""
    from enemy_world_progression import t093_enabled

    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    if t093_enabled(difficulty_cfg):
        return resolve_t093_assignment_hp_out(
            row,
            donor_row,
            difficulty=difficulty,
            npc_by_id=npc_by_id,
            difficulty_cfg=difficulty_cfg,
        )
    map_id = str(row.get("map_id") or "")
    slot_tier = resolve_slot_progression_tier(map_id)
    applied_scale = compute_map_align_scale(slot_tier, difficulty, difficulty_cfg)

    base_hp = npc_base_hp(donor_row)
    model = str(row.get("model") or "")
    min_base = donor_model_min_base_hp(
        model,
        src_cat=str(row.get("src_cat") or ""),
        tgt_cat=str(row.get("tgt_cat") or ""),
        difficulty_cfg=difficulty_cfg,
    )
    if min_base is not None and min_base > base_hp:
        base_hp = min_base
    arena_min = dungeon_boss_arena_min_base_hp(row, difficulty_cfg)
    if arena_min is not None and arena_min > base_hp:
        base_hp = arena_min

    hp_out = scale_int(base_hp, applied_scale) if base_hp > 0 else 0
    boss_floor = boss_slot_hp_floor(
        src_cat=str(row.get("src_cat") or ""),
        src_npc=int(row.get("src_npc") or 0),
        donor_npc=int(row.get("npc") or 0),
        map_id=map_id,
        npc_by_id=npc_by_id,
        difficulty_cfg=difficulty_cfg,
    )
    if boss_floor is not None and boss_floor > hp_out:
        hp_out = boss_floor
    return max(0, int(hp_out))


def assignment_effective_hp(
    row: dict[str, Any],
    donor_row: dict[str, str],
    *,
    difficulty: dict[str, Any],
    npc_by_id: dict[int, dict[str, str]],
    difficulty_cfg: dict[str, Any] | None = None,
) -> int:
    """Combat hp ≈ patched table hp × slot region sp (Journey 1 · 仅 A 套)。"""
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    map_id = str(row.get("map_id") or "")
    slot_tier = resolve_slot_progression_tier(map_id)
    hp_out = resolve_assignment_hp_out(
        row,
        donor_row,
        difficulty=difficulty,
        npc_by_id=npc_by_id,
        difficulty_cfg=difficulty_cfg,
    )
    if hp_out <= 0:
        return 0
    region_mult = region_hp_multiplier_for_slot_tier(
        slot_tier, difficulty_cfg, map_id=map_id
    )
    return max(1, int(round(hp_out * region_mult)))


def rune_category_uses_hp_balance(
    tgt_cat: str,
    difficulty_cfg: dict[str, Any] | None = None,
) -> bool:
    """T-058：该池是否走对称 HP 卢恩（不与地图 tier 卢恩叠乘）。"""
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    excluded = {
        str(x)
        for x in (
            difficulty_cfg.get("rune_hp_scale_exclude_categories") or ["night"]
        )
    }
    return str(tgt_cat or "trash") not in excluded


def assignment_final_effective_hp(
    row: dict[str, Any],
    donor_row: dict[str, str],
    *,
    difficulty: dict[str, Any],
    npc_by_id: dict[int, dict[str, str]],
    difficulty_cfg: dict[str, Any] | None = None,
) -> int:
    """最终有效血（含 T-062 B 套 lift）；供 T-058 卢恩对齐。"""
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    map_id = str(row.get("map_id") or "")
    slot_tier = resolve_slot_progression_tier(map_id)
    adaptive = compute_row_adaptive_lift(
        row,
        donor_row,
        difficulty=difficulty,
        npc_by_id=npc_by_id,
        difficulty_cfg=difficulty_cfg,
    )
    hp_out = resolve_adaptive_hp_out(
        row,
        donor_row,
        difficulty=difficulty,
        npc_by_id=npc_by_id,
        difficulty_cfg=difficulty_cfg,
        lift=float(adaptive.get("lift") or 0.0),
        donor_eff_hp=int(adaptive.get("donor_eff_hp") or 0),
        anchor_eff_hp=int(adaptive.get("anchor_eff_hp") or 0),
    )
    if hp_out <= 0:
        return 0
    region_mult = region_hp_multiplier_for_slot_tier(
        slot_tier, difficulty_cfg, map_id=map_id
    )
    return max(1, int(round(hp_out * region_mult)))


_DEFAULT_RUNE_HP_REFERENCE_BASE: dict[str, int] = {
    "trash": 700,
    "elite": 2500,
    "night": 1100,
    "evergaol": 15000,
    "minor_boss": 13000,
    "major_boss": 25000,
    "cnv_special": 20000,
}


def reference_effective_hp_for_tgt(
    tgt_cat: str,
    map_id: str,
    *,
    difficulty: dict[str, Any],
    difficulty_cfg: dict[str, Any] | None = None,
) -> int:
    """Typical effective hp for ``tgt_cat`` on this map (hp-based rune anchor)."""
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    table = difficulty_cfg.get("rune_hp_reference_base") or _DEFAULT_RUNE_HP_REFERENCE_BASE
    try:
        ref_base = int(table.get(str(tgt_cat), table.get("trash", 700)))
    except (TypeError, ValueError):
        ref_base = 700
    try:
        ref_tier = int(difficulty_cfg.get("rune_hp_reference_tier", 5))
    except (TypeError, ValueError):
        ref_tier = 5

    slot_tier = resolve_slot_progression_tier(map_id)
    applied_scale = compute_map_align_scale(slot_tier, difficulty, difficulty_cfg)
    hp_out = scale_int(ref_base, applied_scale)
    slot_mult = tier_stat_multiplier(slot_tier, difficulty_cfg)
    ref_mult = tier_stat_multiplier(ref_tier, difficulty_cfg)
    if ref_mult > 0:
        hp_out = scale_int(hp_out, slot_mult / ref_mult)
    region_mult = region_hp_multiplier_for_slot_tier(slot_tier, difficulty_cfg)
    return max(1, int(round(hp_out * region_mult)))


def scale_rune_by_assignment_hp(
    amount: int,
    row: dict[str, Any],
    donor_row: dict[str, str],
    *,
    difficulty: dict[str, Any],
    npc_by_id: dict[int, dict[str, str]],
    difficulty_cfg: dict[str, Any] | None = None,
) -> int:
    """T-058：按最终有效血对称缩放卢恩；6 池改原血同比（2026-09-23）。"""
    if amount <= 0:
        return 0
    tgt_cat = str(row.get("tgt_cat") or "trash")
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()

    # 6 池：rune_out = 原卢恩 × (弱化后血 / 原血)
    if tgt_cat == "major_boss":
        adaptive = compute_row_adaptive_lift(
            row,
            donor_row,
            difficulty=difficulty,
            npc_by_id=npc_by_id,
            difficulty_cfg=difficulty_cfg,
        )
        # 原血：捐皮弱化前有效血（adaptive.donor_eff_hp）；T-093 路径下与目标对齐则比值≈1
        orig_hp = int(adaptive.get("donor_eff_hp") or 0)
        if orig_hp <= 0:
            orig_hp = assignment_effective_hp(
                row,
                donor_row,
                difficulty=difficulty,
                npc_by_id=npc_by_id,
                difficulty_cfg=difficulty_cfg,
            )
        final_hp = assignment_final_effective_hp(
            row,
            donor_row,
            difficulty=difficulty,
            npc_by_id=npc_by_id,
            difficulty_cfg=difficulty_cfg,
        )
        if orig_hp <= 0 or final_hp <= 0:
            return int(amount)
        return max(1, int(round(int(amount) * float(final_hp) / float(orig_hp))))

    if not rune_category_uses_hp_balance(tgt_cat, difficulty_cfg):
        return int(amount)

    map_id = str(row.get("map_id") or "")
    eff_hp = assignment_final_effective_hp(
        row,
        donor_row,
        difficulty=difficulty,
        npc_by_id=npc_by_id,
        difficulty_cfg=difficulty_cfg,
    )
    ref_hp = reference_effective_hp_for_tgt(
        tgt_cat,
        map_id,
        difficulty=difficulty,
        difficulty_cfg=difficulty_cfg,
    )
    if eff_hp <= 0 or ref_hp <= 0:
        return int(amount)

    ratio = eff_hp / ref_hp
    try:
        power = float(difficulty_cfg.get("rune_hp_scale_power", 0.9))
    except (TypeError, ValueError):
        power = 0.9
    try:
        min_factor = float(difficulty_cfg.get("rune_hp_scale_min", 0.25))
    except (TypeError, ValueError):
        min_factor = 0.25
    try:
        max_factor = float(difficulty_cfg.get("rune_hp_scale_max", 2.5))
    except (TypeError, ValueError):
        max_factor = 2.5

    # T-058：默认对称；配置仍可点名 boost_only（默认空）
    boost_only = {
        str(x)
        for x in (difficulty_cfg.get("rune_hp_scale_boost_only_categories") or [])
    }
    if tgt_cat in boost_only and ratio <= 1.0:
        out = int(amount)
    else:
        factor = ratio**power if ratio > 0 else 1.0
        factor = max(min_factor, min(max_factor, factor))
        out = max(1, int(round(amount * factor)))

    # 同图 rph 封顶：非主线池不应高于荷莱露档太多
    if bool(difficulty_cfg.get("rune_rph_cap_vs_major", True)):
        major_ref = reference_effective_hp_for_tgt(
            "major_boss",
            map_id,
            difficulty=difficulty,
            difficulty_cfg=difficulty_cfg,
        )
        try:
            major_runes = int(difficulty_cfg.get("rune_major_baseline", 12000))
        except (TypeError, ValueError):
            major_runes = 12000
        if major_ref > 0 and major_runes > 0:
            headroom_table = dict(
                difficulty_cfg.get("rune_rph_cap_headroom_by_category") or {}
            )
            try:
                headroom = float(headroom_table.get(tgt_cat, 1.0))
            except (TypeError, ValueError):
                headroom = 1.0
            major_rph = major_runes / float(major_ref)
            cap = max(1, int(round(eff_hp * major_rph * headroom)))
            out = min(out, cap, major_runes)

    # 洞窟真 Boss 战点保底（防对称缩放压穿）
    if (
        str(row.get("src_cat") or "") == "minor_boss"
        and tgt_cat == "minor_boss"
        and _DUNGEON_BOSS_ARENA_SLOT_RE.match(str(row.get("entity_name") or ""))
        and any(map_id.lower().startswith(p) for p in _DUNGEON_MAP_PREFIXES)
    ):
        try:
            floor = int(difficulty_cfg.get("rune_arena_boss_floor", 2000))
        except (TypeError, ValueError):
            floor = 2000
        if floor > 0:
            out = max(out, floor)

    return max(1, int(out))


def donor_model_min_base_hp(
    model: str,
    *,
    src_cat: str,
    tgt_cat: str,
    difficulty_cfg: dict[str, Any] | None = None,
) -> int | None:
    """Per-model Boss 捐皮 hp 下限（如鲜血贵族 NpcParam 仅 582）。"""
    if tgt_cat != "minor_boss" and src_cat not in BOSS_SLOT_SRC_CATEGORIES:
        return None
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    table = difficulty_cfg.get("minor_boss_donor_min_base_hp_by_prefix") or {}
    model_l = (model or "").lower()
    best: int | None = None
    for prefix, raw_min in table.items():
        try:
            min_hp = int(raw_min)
        except (TypeError, ValueError):
            continue
        if min_hp <= 0:
            continue
        if model_l.startswith(str(prefix).lower()):
            best = max(best or 0, min_hp)
    return best


def adaptive_stat_config(difficulty_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """T-062 ``adaptive_stat_anchor`` 段（默认开启）。"""
    cfg = load_difficulty_cfg() if difficulty_cfg is None else difficulty_cfg
    raw = dict(cfg.get("adaptive_stat_anchor") or {})
    defaults: dict[str, Any] = {
        "enabled": True,
        "adaptive_lift_power": 0.70,
        "overshoot_cap": 1.15,
        "trash_overshoot_clamp": False,
        "poise_anchor_reference_tier": 5,
        "attack_sp_min_lift": 0.2,
        "attack_sp_skip_categories": ["major_boss"],
        "poise_anchor_base": {
            "trash": 28,
            "elite": 55,
            "night": 35,
            "minor_boss": 100,
            "evergaol": 120,
            "major_boss": 180,
            "cnv_special": 160,
        },
        "attack_sp_by_tier": {
            "1": 0,
            "2": 0,
            "3": 8501,
            "4": 8501,
            "5": 13073,
            "6": 13073,
            "7": 8510,
            "8": 8510,
            "9": 8510,
        },
        "attack_sp_rates": {
            "8501": 1.05,
            "13073": 1.05,
            "8510": 1.20,
            "19565": 1.25,
            "7302": 1.202198,
            "20007131": 4.641667,
        },
    }
    out = {**defaults, **raw}
    out["enabled"] = bool(out.get("enabled", True))
    try:
        out["adaptive_lift_power"] = max(0.05, float(out.get("adaptive_lift_power", 0.70)))
    except (TypeError, ValueError):
        out["adaptive_lift_power"] = 0.70
    try:
        out["overshoot_cap"] = max(1.0, float(out.get("overshoot_cap", 1.15)))
    except (TypeError, ValueError):
        out["overshoot_cap"] = 1.15
    out["trash_overshoot_clamp"] = bool(out.get("trash_overshoot_clamp", False))
    try:
        out["poise_anchor_reference_tier"] = max(
            1, min(9, int(out.get("poise_anchor_reference_tier", 5)))
        )
    except (TypeError, ValueError):
        out["poise_anchor_reference_tier"] = 5
    try:
        out["attack_sp_min_lift"] = max(0.0, min(1.0, float(out.get("attack_sp_min_lift", 0.2))))
    except (TypeError, ValueError):
        out["attack_sp_min_lift"] = 0.2
    out["attack_sp_skip_categories"] = [
        str(x) for x in (out.get("attack_sp_skip_categories") or ["major_boss"])
    ]
    out["poise_anchor_base"] = dict(defaults["poise_anchor_base"]) | dict(
        out.get("poise_anchor_base") or {}
    )
    out["attack_sp_by_tier"] = dict(defaults["attack_sp_by_tier"]) | {
        str(k): v for k, v in dict(out.get("attack_sp_by_tier") or {}).items()
    }
    raw_rates = dict(out.get("attack_sp_rates") or defaults.get("attack_sp_rates") or {})
    rates: dict[str, float] = {}
    for raw_id, raw_rate in raw_rates.items():
        try:
            rates[str(int(raw_id))] = float(raw_rate)
        except (TypeError, ValueError):
            continue
    out["attack_sp_rates"] = rates
    return out


_DEFAULT_CLEARCOUNT_HP: dict[int, float] = {
    0: 1.0,
    1: 1.05,
    2: 1.1,
    3: 1.15,
    4: 1.2,
    5: 1.25,
    6: 1.3,
    7: 1.4,
}
_DEFAULT_CLEARCOUNT_ATK: dict[int, float] = {
    0: 1.0,
    1: 1.05,
    2: 1.1,
    3: 1.15,
    4: 1.2,
    5: 1.25,
    6: 1.3,
    7: 1.45,
}


def target_progression_config(
    difficulty_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """T-065 ``target_progression_curve`` 段。"""
    cfg = load_difficulty_cfg() if difficulty_cfg is None else difficulty_cfg
    raw = dict(cfg.get("target_progression_curve") or {})
    defaults: dict[str, Any] = {
        "enabled": False,
        "tier_weight": 0.35,
        "ng_weight": 0.65,
        "reference_ng": 7,
        "cap_hp_ratio": 7.5,
        "cap_poise": 2.0,
        "cap_attack": 1.5,
        "cap_rune": 10.0,
        "j1_base_sp": "7010",
        "disable_adaptive_lift": True,
        "clearcount_hp": dict(_DEFAULT_CLEARCOUNT_HP),
        "clearcount_attack": dict(_DEFAULT_CLEARCOUNT_ATK),
    }
    out = {**defaults, **raw}
    out["enabled"] = bool(out.get("enabled", False))
    try:
        out["reference_ng"] = max(0, min(7, int(out.get("reference_ng", 7))))
    except (TypeError, ValueError):
        out["reference_ng"] = 7
    out["disable_adaptive_lift"] = bool(out.get("disable_adaptive_lift", True))
    out["j1_base_sp"] = str(out.get("j1_base_sp", "7010"))
    hp_cc = dict(_DEFAULT_CLEARCOUNT_HP)
    for k, v in dict(out.get("clearcount_hp") or {}).items():
        try:
            hp_cc[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    out["clearcount_hp"] = hp_cc
    atk_cc = dict(_DEFAULT_CLEARCOUNT_ATK)
    for k, v in dict(out.get("clearcount_attack") or {}).items():
        try:
            atk_cc[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    out["clearcount_attack"] = atk_cc
    return out


def target_progression_enabled(difficulty_cfg: dict[str, Any] | None = None) -> bool:
    return bool(target_progression_config(difficulty_cfg).get("enabled", False))


def target_curve_progress(tier: int, ng: int, curve_cfg: dict[str, Any]) -> float:
    try:
        w_t = float(curve_cfg.get("tier_weight", 0.35))
        w_n = float(curve_cfg.get("ng_weight", 0.65))
    except (TypeError, ValueError):
        w_t, w_n = 0.35, 0.65
    tier_i = max(1, min(9, int(tier)))
    ng_i = max(0, min(7, int(ng)))
    return w_t * (tier_i - 1) / 8.0 + w_n * ng_i / 7.0


def target_curve_factor(
    cap: float,
    tier: int,
    ng: int,
    curve_cfg: dict[str, Any],
) -> float:
    try:
        cap_f = float(cap)
    except (TypeError, ValueError):
        cap_f = 1.0
    return 1.0 + (cap_f - 1.0) * target_curve_progress(tier, ng, curve_cfg)


def target_map_tier_mult(tier: int, curve_cfg: dict[str, Any]) -> float:
    """仅地图档分量（T1·一周目 = 1.0）。"""
    try:
        cap = float(curve_cfg.get("cap_hp_ratio", 7.5))
        w_t = float(curve_cfg.get("tier_weight", 0.35))
    except (TypeError, ValueError):
        cap, w_t = 7.5, 0.35
    t = max(1, min(9, int(tier)))
    return 1.0 + (cap - 1.0) * w_t * (t - 1) / 8.0


def _nearest_sp_id(target_mult: float, pool: set[str]) -> str:
    if not pool:
        return "7010"
    best_id = "7010"
    best_diff = float("inf")
    for sid in pool:
        mult = float(REGION_HP_MULT.get(sid, 1.0))
        diff = abs(mult - target_mult)
        if diff < best_diff:
            best_diff = diff
            best_id = sid
    return best_id


def build_curve_sp_bindings(
    difficulty_cfg: dict[str, Any] | None = None,
    curve_cfg: dict[str, Any] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """T-065：按目标曲线生成全图 J1 / NG+ 区域 sp 绑档表（全局，非单怪）。"""
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    curve_cfg = curve_cfg or target_progression_config(difficulty_cfg)
    j1_pool = region_sp_effect_ids(difficulty_cfg)
    ng_pool = ng_region_sp_effect_ids(difficulty_cfg)
    if not ng_pool:
        ng_pool = {
            sid
            for sid in REGION_HP_MULT
            if NG_REGION_SP_MIN <= int(sid) <= NG_REGION_SP_MAX
        }
    base_sp = str(curve_cfg.get("j1_base_sp", "7010"))
    base_j1 = float(REGION_HP_MULT.get(base_sp, 3.340303))
    ref_ng = int(curve_cfg.get("reference_ng", 7))
    cc_table = curve_cfg.get("clearcount_hp") or _DEFAULT_CLEARCOUNT_HP
    cc_ref = float(cc_table.get(ref_ng, cc_table.get(7, 1.4)))
    try:
        cap_hp = float(curve_cfg.get("cap_hp_ratio", 7.5))
    except (TypeError, ValueError):
        cap_hp = 7.5

    j1_by_tier: dict[str, str] = {}
    ng_by_tier: dict[str, str] = {}
    for tier in range(1, 10):
        t_key = str(tier)
        map_mult = target_map_tier_mult(tier, curve_cfg)
        j1_target = base_j1 * map_mult
        j1_id = _nearest_sp_id(j1_target, j1_pool)
        j1_by_tier[t_key] = j1_id
        j1_actual = float(REGION_HP_MULT.get(j1_id, base_j1))

        combined = target_curve_factor(cap_hp, tier, ref_ng, curve_cfg)
        if j1_actual > 0 and cc_ref > 0:
            ng_target = combined * base_j1 / (j1_actual * cc_ref)
        else:
            ng_target = 1.0
        ng_cap = max(float(REGION_HP_MULT.get(sid, 1.0)) for sid in ng_pool)
        ng_target = min(ng_target, ng_cap)
        ng_by_tier[t_key] = _nearest_sp_id(ng_target, ng_pool)

    return j1_by_tier, ng_by_tier


def tier_to_region_sp_effect(tier: int, difficulty_cfg: dict[str, Any] | None = None) -> str:
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    if target_progression_enabled(difficulty_cfg):
        j1_table, _ = build_curve_sp_bindings(difficulty_cfg)
        t_key = str(max(1, min(9, int(tier))))
        return str(j1_table.get(t_key, j1_table.get("5", "7010")))
    table = difficulty_cfg.get("tier_to_region_sp_effect") or {}
    return str(table.get(str(tier), table.get("5", "7080")))


def tier_to_ng_region_sp_effect(tier: int, difficulty_cfg: dict[str, Any] | None = None) -> str:
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    if target_progression_enabled(difficulty_cfg):
        _, ng_table = build_curve_sp_bindings(difficulty_cfg)
        t_key = str(max(1, min(9, int(tier))))
        return str(ng_table.get(t_key, ng_table.get("5", "7480")))
    table = difficulty_cfg.get("tier_to_ng_region_sp_effect") or {}
    return str(table.get(str(tier), table.get("5", "7480")))


def engine_hp_mult_at_ng(
    slot_tier: int,
    ng_cycle: int,
    *,
    difficulty_cfg: dict[str, Any] | None = None,
    curve_cfg: dict[str, Any] | None = None,
) -> float:
    """引擎有效血倍率：J1 区域 ×（NG+ 时 NG 区域 × ClearCount 血倍）。"""
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    curve_cfg = curve_cfg or target_progression_config(difficulty_cfg)
    j1_id = tier_to_region_sp_effect(slot_tier, difficulty_cfg)
    j1 = float(REGION_HP_MULT.get(j1_id, 1.0))
    ng_i = max(0, min(7, int(ng_cycle)))
    if ng_i <= 0:
        return j1
    ng_id = tier_to_ng_region_sp_effect(slot_tier, difficulty_cfg)
    ng_sp = float(REGION_HP_MULT.get(ng_id, 1.0))
    cc_table = curve_cfg.get("clearcount_hp") or _DEFAULT_CLEARCOUNT_HP
    cc = float(cc_table.get(ng_i, cc_table.get(7, 1.4)))
    return j1 * ng_sp * cc


def resolve_target_curve_poise_out(
    donor_row: dict[str, str],
    *,
    row: dict[str, Any],
    difficulty: dict[str, Any],
    difficulty_cfg: dict[str, Any] | None = None,
) -> int:
    """T-065：韧性按 T1·一周目锚 × 曲线（周目不叠引擎倍）。"""
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    curve_cfg = target_progression_config(difficulty_cfg)
    map_id = str(row.get("map_id") or "")
    slot_tier = resolve_slot_progression_tier(map_id)
    tgt_cat = str(row.get("tgt_cat") or "trash")
    ref_ng = int(curve_cfg.get("reference_ng", 7))
    applied_scale = compute_map_align_scale(slot_tier, difficulty, difficulty_cfg)
    base_poise = npc_base_def_flick(donor_row)
    donor_poise_eff = float(scale_int(base_poise, applied_scale)) if base_poise > 0 else 0.0

    poise_anchor_t1 = resolve_poise_anchor(
        1,
        tgt_cat,
        difficulty=difficulty,
        difficulty_cfg=difficulty_cfg,
    )
    try:
        cap_poise = float(curve_cfg.get("cap_poise", 2.0))
    except (TypeError, ValueError):
        cap_poise = 2.0
    target_eff = poise_anchor_t1 * target_curve_factor(cap_poise, slot_tier, ref_ng, curve_cfg)
    if applied_scale <= 0:
        return max(0, int(round(max(donor_poise_eff, target_eff))))
    poise_out = max(0, int(round(target_eff / applied_scale)))
    if donor_poise_eff > 0:
        poise_out = max(poise_out, int(round(donor_poise_eff / applied_scale)) if applied_scale > 0 else 0)
    return poise_out


def scale_rune_by_target_curve(
    amount: int,
    row: dict[str, Any],
    *,
    difficulty: dict[str, Any] | None = None,
    difficulty_cfg: dict[str, Any] | None = None,
) -> int:
    """T-065：击杀卢恩按目标曲线（取代 T-058 / 地图档卢恩）。"""
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    curve_cfg = target_progression_config(difficulty_cfg)
    if not curve_cfg.get("enabled"):
        return max(0, int(amount))
    map_id = str(row.get("map_id") or "")
    slot_tier = resolve_slot_progression_tier(map_id)
    ref_ng = int(curve_cfg.get("reference_ng", 7))
    if amount <= 0:
        return 0
    try:
        cap_rune = float(curve_cfg.get("cap_rune", 10.0))
    except (TypeError, ValueError):
        cap_rune = 10.0
    factor = target_curve_factor(cap_rune, slot_tier, ref_ng, curve_cfg)
    return max(1, int(round(amount * factor)))


def assignment_effective_hp_at_ng(
    table_hp: int,
    slot_tier: int,
    ng_cycle: int,
    *,
    difficulty_cfg: dict[str, Any] | None = None,
) -> int:
    """表 hp × 区域/ClearCount（与 T-065 flatten 一致）。"""
    if table_hp <= 0:
        return 0
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    mult = engine_hp_mult_at_ng(slot_tier, ng_cycle, difficulty_cfg=difficulty_cfg)
    return max(1, int(round(table_hp * mult)))


def compute_t093_stat_lift_mult(
    row: dict[str, Any],
    donor_row: dict[str, str],
    *,
    difficulty: dict[str, Any],
    npc_by_id: dict[int, dict[str, str]],
    difficulty_cfg: dict[str, Any] | None = None,
) -> float:
    """韧/视/嗅等：周目层 → 硬帽后，滑条×地图对层前血分算相乘（T-099 D）。"""
    from enemy_whitelist_hp import resolve_donor_baseline_effective_hp
    from enemy_world_progression import (
        asymmetric_layer_lift_mult,
        compute_slider_lift_mult,
        map_layer_lift_mult,
        nominal_journey_stat_mult,
        nominal_map_stat_mult,
        resolve_bracket_cap_mult,
        resolve_journey_tier,
        resolve_map_tier_t093,
        t093_config,
        t094_config,
        t094_enabled,
    )

    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    t093 = t093_config(difficulty_cfg)
    h_ref = float(t093.get("lift_h_ref", 2500.0))
    alpha = float(t093.get("lift_alpha", 0.5))
    base = resolve_donor_baseline_effective_hp(row, donor_row, npc_by_id=npc_by_id)
    if base <= 0:
        return 1.0

    out = 1.0
    h = float(base)
    map_nom = 1.0
    use_t094 = t094_enabled(difficulty_cfg)
    if use_t094:
        t094 = t094_config(difficulty_cfg)
        h_ref_l = float(t094.get("layer_lift_h_ref", h_ref))
        alpha_l = float(t094.get("layer_lift_alpha", alpha))
        map_id = str(row.get("map_id") or "")
        map_tier = resolve_map_tier_t093(map_id)
        map_nom = nominal_map_stat_mult(map_tier, difficulty_cfg=difficulty_cfg)
        j_nom = nominal_journey_stat_mult(
            resolve_journey_tier(difficulty), difficulty_cfg=difficulty_cfg
        )
        j_eff = asymmetric_layer_lift_mult(h, j_nom, h_ref=h_ref_l, alpha=alpha_l)
        out *= j_eff
        out = min(
            out,
            resolve_bracket_cap_mult(
                base, kind="stat", difficulty_cfg=difficulty_cfg
            ),
        )
        h = float(base) * out

    # T-099 D：对层前血（h）分算滑条与地图，再乘进 out
    h_pre = h
    user_mult = float(difficulty.get("user_mult", 1.0))
    slider = compute_slider_lift_mult(
        h_pre,
        user_mult,
        h_ref=h_ref,
        alpha=alpha,
    )
    if use_t094:
        m_eff = map_layer_lift_mult(h_pre, map_nom, difficulty_cfg=difficulty_cfg)
    else:
        m_eff = 1.0
    out *= float(slider) * float(m_eff)

    return max(0.01, float(out))


def compute_t093_attack_lift_mult(
    row: dict[str, Any],
    donor_row: dict[str, str],
    *,
    difficulty: dict[str, Any],
    npc_by_id: dict[int, dict[str, str]],
    difficulty_cfg: dict[str, Any] | None = None,
) -> float:
    """T-096 地图攻倍率（仅地图层 lift+帽）；周目攻由引擎 ClearCount，mod 不写 journey。

    攻击路径无全局滑条乘子；地图层对白名单底血算（与 HP T-099 分算一致、无滑条打架）。
    """
    from enemy_whitelist_hp import resolve_donor_baseline_effective_hp
    from enemy_world_progression import (
        map_layer_lift_mult,
        nominal_map_atk_mult,
        resolve_bracket_cap_mult,
        resolve_map_tier_t093,
        t094_config,
        t094_enabled,
    )

    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    base = resolve_donor_baseline_effective_hp(row, donor_row, npc_by_id=npc_by_id)
    if base <= 0:
        return 1.0

    if not t094_enabled(difficulty_cfg):
        return 1.0

    map_id = str(row.get("map_id") or "")
    map_tier = resolve_map_tier_t093(map_id)
    m_nom = nominal_map_atk_mult(map_tier, difficulty_cfg=difficulty_cfg)
    m_eff = map_layer_lift_mult(float(base), m_nom, difficulty_cfg=difficulty_cfg)
    m_eff = min(
        m_eff,
        resolve_bracket_cap_mult(
            base, kind="attack", difficulty_cfg=difficulty_cfg
        ),
    )
    return max(0.01, float(m_eff))


_ATTACK_SP_RATES_FALLBACK: dict[int, float] = {
    8501: 1.05,
    13073: 1.05,
    8510: 1.20,
}


@lru_cache(maxsize=4096)
def _sp_max_hp_rate(sp_id: int) -> float:
    """SpEffect maxHpRate; missing/1.0 → safe for attack_sp."""
    from dlc_donor_pool import load_sp_hp_rates

    rates = load_sp_hp_rates()
    try:
        return float(rates.get(str(int(sp_id)), 1.0))
    except (TypeError, ValueError):
        return 1.0


def _attack_sp_has_hp_mult(sp_id: int) -> bool:
    """True if SpEffect also scales HP (must not be used as pure attack_sp)."""
    rate = _sp_max_hp_rate(sp_id)
    return abs(rate - 1.0) > 1e-6


def _region_hp_sp_ids(difficulty_cfg: dict[str, Any] | None = None) -> frozenset[int]:
    """J1/NG+ region maxHpRate ids — must not be used as attack_sp (engine stacks HP)."""
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    ids: set[int] = set()
    for sid in region_sp_effect_ids(difficulty_cfg):
        try:
            ids.add(int(sid))
        except (TypeError, ValueError):
            continue
    for sid in ng_region_sp_effect_ids(difficulty_cfg):
        try:
            ids.add(int(sid))
        except (TypeError, ValueError):
            continue
    return frozenset(ids)


_FORBIDDEN_ATTACK_SP_CACHE: frozenset[int] | None = None
_ATTACK_SP_RATE_TABLE_CACHE: dict[int, float] | None = None


def _build_forbidden_attack_sp_ids(
    difficulty_cfg: dict[str, Any],
) -> frozenset[int]:
    """Region HP ids + any configured attack_sp whose maxHpRate ≠ 1."""
    banned = set(_region_hp_sp_ids(difficulty_cfg))
    cfg = adaptive_stat_config(difficulty_cfg)
    for raw_id in (cfg.get("attack_sp_rates") or {}):
        try:
            sp_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if sp_id > 0 and _attack_sp_has_hp_mult(sp_id):
            banned.add(sp_id)
    for raw_id in (cfg.get("attack_sp_by_tier") or {}).values():
        try:
            sp_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if sp_id > 0 and _attack_sp_has_hp_mult(sp_id):
            banned.add(sp_id)
    return frozenset(banned)


def _forbidden_attack_sp_ids(difficulty_cfg: dict[str, Any] | None = None) -> frozenset[int]:
    global _FORBIDDEN_ATTACK_SP_CACHE
    if difficulty_cfg is None:
        if _FORBIDDEN_ATTACK_SP_CACHE is not None:
            return _FORBIDDEN_ATTACK_SP_CACHE
        difficulty_cfg = load_difficulty_cfg()
        _FORBIDDEN_ATTACK_SP_CACHE = _build_forbidden_attack_sp_ids(difficulty_cfg)
        return _FORBIDDEN_ATTACK_SP_CACHE
    return _build_forbidden_attack_sp_ids(difficulty_cfg)


def _attack_sp_rate_table(difficulty_cfg: dict[str, Any] | None = None) -> dict[int, float]:
    global _ATTACK_SP_RATE_TABLE_CACHE
    if difficulty_cfg is None:
        if _ATTACK_SP_RATE_TABLE_CACHE is not None:
            return _ATTACK_SP_RATE_TABLE_CACHE
        difficulty_cfg = load_difficulty_cfg()
        _ATTACK_SP_RATE_TABLE_CACHE = _build_attack_sp_rate_table(difficulty_cfg)
        return _ATTACK_SP_RATE_TABLE_CACHE
    return _build_attack_sp_rate_table(difficulty_cfg)


def _build_attack_sp_rate_table(difficulty_cfg: dict[str, Any]) -> dict[int, float]:
    cfg = adaptive_stat_config(difficulty_cfg)
    banned = _forbidden_attack_sp_ids(difficulty_cfg)
    out: dict[int, float] = {}
    for raw_id, raw_rate in (cfg.get("attack_sp_rates") or {}).items():
        try:
            sp_id = int(raw_id)
            rate = float(raw_rate)
        except (TypeError, ValueError):
            continue
        if sp_id <= 0 or rate <= 0 or sp_id in banned or _attack_sp_has_hp_mult(sp_id):
            continue
        out[sp_id] = rate
    for raw_id in (cfg.get("attack_sp_by_tier") or {}).values():
        try:
            sp_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if sp_id <= 0 or sp_id in banned or _attack_sp_has_hp_mult(sp_id):
            continue
        if sp_id not in out:
            out[sp_id] = float(_ATTACK_SP_RATES_FALLBACK.get(sp_id, 1.05))
    return out


def _pick_attack_sp_for_rate(
    required_rate: float,
    difficulty_cfg: dict[str, Any] | None = None,
) -> tuple[int, float] | None:
    """选 physicsAttackPowerRate 最接近且不低于 required 的 sp；required≤1 不写 sp。

    Never picks SpEffects with maxHpRate≠1 (even if attack pool misconfigured).
    If no pure-attack sp meets required_rate, use the strongest pure-attack available
    (under-boost) rather than a HP-scaling area package.
    """
    if required_rate <= 1.001:
        return None
    table = _attack_sp_rate_table(difficulty_cfg)
    if not table:
        return None
    banned = _forbidden_attack_sp_ids(difficulty_cfg)
    candidates = [
        (sp_id, rate)
        for sp_id, rate in table.items()
        if sp_id not in banned
        and not _attack_sp_has_hp_mult(sp_id)
        and rate >= required_rate - 1e-6
    ]
    if candidates:
        sp_id, rate = min(candidates, key=lambda item: item[1])
        return sp_id, rate
    safe = {
        k: v
        for k, v in table.items()
        if k not in banned and not _attack_sp_has_hp_mult(k)
    }
    if not safe:
        return None
    sp_id = max(safe, key=lambda k: safe[k])
    return sp_id, safe[sp_id]


def compute_adaptive_lift(
    donor_eff_hp: int,
    anchor_eff_hp: int,
    *,
    difficulty_cfg: dict[str, Any] | None = None,
) -> float:
    """T-062 anchor lift (legacy) or T-093 returns 0 — slider handled in hp path."""
    from enemy_world_progression import t093_enabled

    if t093_enabled(difficulty_cfg):
        return 0.0
    cfg = adaptive_stat_config(difficulty_cfg)
    if not cfg.get("enabled", True):
        return 0.0
    if donor_eff_hp <= 0 or anchor_eff_hp <= 0:
        return 0.0
    cap = float(cfg["overshoot_cap"])
    r_raw = float(donor_eff_hp) / float(anchor_eff_hp)
    r = max(0.0, min(cap, r_raw))
    alpha = float(cfg["adaptive_lift_power"])
    if abs(r - 1.0) < 1e-9:
        return 0.0
    if r < 1.0:
        return max(0.0, min(1.0, 1.0 - (r**alpha)))
    return max(0.0, min(1.0, 1.0 - ((1.0 / r) ** alpha)))


def resolve_poise_anchor(
    slot_tier: int,
    tgt_cat: str,
    *,
    difficulty: dict[str, Any],
    difficulty_cfg: dict[str, Any] | None = None,
) -> float:
    """韧性锚点（已含 baseline×user_mult 的有效空间）。"""
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    cfg = adaptive_stat_config(difficulty_cfg)
    base_table = cfg.get("poise_anchor_base") or {}
    try:
        base = float(base_table.get(str(tgt_cat), base_table.get("trash", 28)))
    except (TypeError, ValueError):
        base = 28.0
    ref_tier = int(cfg.get("poise_anchor_reference_tier", 5))
    slot_mult = tier_stat_multiplier(slot_tier, difficulty_cfg)
    ref_mult = tier_stat_multiplier(ref_tier, difficulty_cfg)
    if ref_mult > 0:
        base *= slot_mult / ref_mult
    applied = compute_map_align_scale(slot_tier, difficulty, difficulty_cfg)
    return max(0.0, base * applied)


def compute_row_adaptive_lift(
    row: dict[str, Any],
    donor_row: dict[str, str],
    *,
    difficulty: dict[str, Any],
    npc_by_id: dict[int, dict[str, str]],
    difficulty_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """算 A 套有效血 → lift；结果写入 ``row['_adaptive_lift']`` 供 Think 共用。"""
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    from enemy_world_progression import t093_enabled

    cfg = adaptive_stat_config(difficulty_cfg)
    map_id = str(row.get("map_id") or "")
    slot_tier = resolve_slot_progression_tier(map_id)
    if t093_enabled(difficulty_cfg):
        target_eff = resolve_t093_target_effective_hp(
            row,
            donor_row,
            difficulty=difficulty,
            npc_by_id=npc_by_id,
            difficulty_cfg=difficulty_cfg,
        )
        lift_m = compute_t093_stat_lift_mult(
            row,
            donor_row,
            difficulty=difficulty,
            npc_by_id=npc_by_id,
            difficulty_cfg=difficulty_cfg,
        )
        meta = {
            "enabled": True,
            "lift": 0.0,
            "t093_stat_mult": round(float(lift_m), 6),
            "donor_eff_hp": int(target_eff),
            "anchor_eff_hp": int(target_eff),
            "slot_tier": int(slot_tier),
            "t093": True,
        }
        row["_adaptive_lift"] = 0.0
        row["_t093_stat_mult"] = meta["t093_stat_mult"]
        row["_adaptive_meta"] = meta
        return meta
    donor_eff = assignment_effective_hp(
        row,
        donor_row,
        difficulty=difficulty,
        npc_by_id=npc_by_id,
        difficulty_cfg=difficulty_cfg,
    )
    anchor_eff = reference_effective_hp_for_tgt(
        str(row.get("tgt_cat") or "trash"),
        map_id,
        difficulty=difficulty,
        difficulty_cfg=difficulty_cfg,
    )
    lift = 0.0
    curve_cfg = target_progression_config(difficulty_cfg)
    skip_lift = bool(
        curve_cfg.get("enabled") and curve_cfg.get("disable_adaptive_lift", True)
    )
    if cfg.get("enabled", True) and not skip_lift:
        lift = compute_adaptive_lift(donor_eff, anchor_eff, difficulty_cfg=difficulty_cfg)
    meta = {
        "enabled": bool(cfg.get("enabled", True)),
        "lift": round(float(lift), 4),
        "donor_eff_hp": int(donor_eff),
        "anchor_eff_hp": int(anchor_eff),
        "slot_tier": int(slot_tier),
    }
    row["_adaptive_lift"] = meta["lift"]
    row["_adaptive_meta"] = meta
    return meta


def resolve_adaptive_hp_out(
    row: dict[str, Any],
    donor_row: dict[str, str],
    *,
    difficulty: dict[str, Any],
    npc_by_id: dict[int, dict[str, str]],
    difficulty_cfg: dict[str, Any] | None = None,
    lift: float = 0.0,
    donor_eff_hp: int = 0,
    anchor_eff_hp: int = 0,
) -> int:
    """A 套表 hp 后按 lift 向锚点靠拢；写盘值为表 hp（引擎再乘 region）。"""
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    from enemy_world_progression import t093_enabled

    hp_out = resolve_assignment_hp_out(
        row,
        donor_row,
        difficulty=difficulty,
        npc_by_id=npc_by_id,
        difficulty_cfg=difficulty_cfg,
    )
    if t093_enabled(difficulty_cfg):
        return hp_out
    if lift <= 0 or donor_eff_hp <= 0 or anchor_eff_hp <= 0:
        return hp_out
    target_eff = donor_eff_hp + (anchor_eff_hp - donor_eff_hp) * float(lift)
    map_id = str(row.get("map_id") or "")
    slot_tier = resolve_slot_progression_tier(map_id)
    region_mult = region_hp_multiplier_for_slot_tier(
        slot_tier, difficulty_cfg, map_id=map_id
    )
    if region_mult <= 0:
        return hp_out
    # 有效血空间插值后只反除 region（baseline×user_mult 已含在 A 套 donor_eff 内）
    hp_b = max(1, int(round(target_eff / region_mult)))
    boss_floor = boss_slot_hp_floor(
        src_cat=str(row.get("src_cat") or ""),
        src_npc=int(row.get("src_npc") or 0),
        donor_npc=int(row.get("npc") or 0),
        map_id=map_id,
        npc_by_id=npc_by_id,
        difficulty_cfg=difficulty_cfg,
    )
    if boss_floor is not None and boss_floor > hp_b:
        hp_b = boss_floor
    arena_min = dungeon_boss_arena_min_base_hp(row, difficulty_cfg)
    if arena_min is not None and arena_min > hp_b:
        hp_b = arena_min
    if donor_eff_hp > anchor_eff_hp:
        return hp_b
    return max(hp_out, hp_b)


def resolve_adaptive_poise_out(
    donor_row: dict[str, str],
    *,
    row: dict[str, Any],
    difficulty: dict[str, Any],
    difficulty_cfg: dict[str, Any] | None = None,
    lift: float = 0.0,
    npc_by_id: dict[int, dict[str, str]] | None = None,
) -> int:
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    from enemy_world_progression import t093_enabled

    map_id = str(row.get("map_id") or "")
    slot_tier = resolve_slot_progression_tier(map_id)
    applied_scale = compute_map_align_scale(slot_tier, difficulty, difficulty_cfg)
    base_poise = npc_base_def_flick(donor_row)
    donor_poise_eff = float(scale_int(base_poise, applied_scale)) if base_poise > 0 else 0.0
    if t093_enabled(difficulty_cfg):
        stat_m = compute_t093_stat_lift_mult(
            row,
            donor_row,
            difficulty=difficulty,
            npc_by_id=npc_by_id or {},
            difficulty_cfg=difficulty_cfg,
        )
        if base_poise <= 0:
            return 0
        return max(0, int(round(float(base_poise) * float(stat_m))))
    if lift <= 0 or donor_poise_eff <= 0:
        return int(donor_poise_eff) if donor_poise_eff > 0 else 0
    anchor = resolve_poise_anchor(
        slot_tier,
        str(row.get("tgt_cat") or "trash"),
        difficulty=difficulty,
        difficulty_cfg=difficulty_cfg,
    )
    target = donor_poise_eff + (anchor - donor_poise_eff) * float(lift)
    if applied_scale <= 0:
        return max(0, int(round(target)))
    return max(0, int(round(target / applied_scale)))


def resolve_adaptive_attack_sp(
    donor_row: dict[str, str],
    *,
    row: dict[str, Any],
    lift: float,
    occupied_slots: dict[str, str],
    difficulty_cfg: dict[str, Any] | None = None,
    t093_stat_mult: float = 1.0,
    difficulty: dict[str, Any] | None = None,
    npc_by_id: dict[int, dict[str, str]] | None = None,
) -> tuple[str, str] | None:
    """选空闲 sp 槽写入加攻；T-096：mod_rate = 地图攻（周目仍引擎 ClearCount）。"""
    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    from enemy_world_progression import (
        nominal_journey_atk_mult,
        resolve_journey_tier,
        t093_enabled,
        t094_config,
        t094_enabled,
    )

    cfg = adaptive_stat_config(difficulty_cfg)
    if not cfg.get("enabled", True):
        return None

    tgt_cat = str(row.get("tgt_cat") or "")
    if tgt_cat in set(cfg.get("attack_sp_skip_categories") or []):
        return None

    t094 = t094_config(difficulty_cfg) if t094_enabled(difficulty_cfg) else {}
    map_attack_disabled = bool(
        t094_enabled(difficulty_cfg) and t094.get("disable_map_attack_sp", False)
    )
    diff = difficulty if difficulty is not None else {"enabled": True, "journey_tier": 1}
    npc_by_id = npc_by_id or {}

    sp_id = 0
    if t094_enabled(difficulty_cfg) and not map_attack_disabled:
        map_atk = compute_t093_attack_lift_mult(
            row,
            donor_row,
            difficulty=diff,
            npc_by_id=npc_by_id,
            difficulty_cfg=difficulty_cfg,
        )
        required_rate = float(map_atk)
        picked = _pick_attack_sp_for_rate(required_rate, difficulty_cfg)
        if picked is None:
            return None
        sp_id = picked[0]
    else:
        weak_attack_ok = False
        if map_attack_disabled and t094.get("weak_low_hp_attack_sp", True):
            from enemy_whitelist_hp import resolve_donor_baseline_effective_hp

            base_hp = float(
                resolve_donor_baseline_effective_hp(row, donor_row, npc_by_id=npc_by_id) or 0
            )
            threshold = float(t094.get("weak_hp_cap_threshold", 5000))
            boost = max(0.0, float(t093_stat_mult) - 1.0)
            min_boost = float(t094.get("weak_attack_sp_min_boost", 0.05))
            if base_hp > 0 and base_hp < threshold and boost >= min_boost:
                weak_attack_ok = True
        if map_attack_disabled and not weak_attack_ok:
            return None
        if t093_enabled(difficulty_cfg):
            boost = max(0.0, float(t093_stat_mult) - 1.0)
            min_lift = (
                float(t094.get("weak_attack_sp_min_boost", 0.05))
                if weak_attack_ok
                else float(cfg["attack_sp_min_lift"])
            )
            if boost < min_lift:
                return None
            lift = min(1.0, boost)
        elif float(lift) < float(cfg["attack_sp_min_lift"]):
            return None
        slot_tier = resolve_slot_progression_tier(str(row.get("map_id") or ""))
        attack_tier = max(1, min(9, int(round(1 + (slot_tier - 1) * float(lift)))))
        raw_id = (cfg.get("attack_sp_by_tier") or {}).get(str(attack_tier), 0)
        try:
            sp_id = int(raw_id)
        except (TypeError, ValueError):
            sp_id = 0

    if sp_id <= 0:
        return None
    sp_s = str(sp_id)
    if sp_s in {str(v) for v in sp_effect_ids(donor_row)}:
        return None
    if sp_s in {str(v) for v in occupied_slots.values() if str(v) not in ("", "0", "-1")}:
        return None

    merged = dict(donor_row)
    for key, val in occupied_slots.items():
        merged[key] = str(val)
    for key in _iter_sp_effect_slot_keys(merged):
        cur = str(merged.get(key) or "")
        if cur not in ("", "0", "-1"):
            continue
        return key, sp_s
    return None


def compute_assignment_patch(
    row: dict[str, Any],
    donor_row: dict[str, str],
    *,
    soul_out: int,
    difficulty: dict[str, Any],
    npc_by_id: dict[int, dict[str, str]],
    difficulty_cfg: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not difficulty.get("enabled", True):
        return None
    if int(row.get("npc") or 0) <= 0:
        return None
    if row.get("suppress_mount") or row.get("suppress_decorative"):
        return None

    difficulty_cfg = difficulty_cfg or load_difficulty_cfg()
    from enemy_world_progression import t093_enabled

    map_id = str(row.get("map_id") or "")
    slot_tier = resolve_slot_progression_tier(map_id)
    applied_scale = compute_map_align_scale(slot_tier, difficulty, difficulty_cfg)

    adaptive = compute_row_adaptive_lift(
        row,
        donor_row,
        difficulty=difficulty,
        npc_by_id=npc_by_id,
        difficulty_cfg=difficulty_cfg,
    )
    lift = float(adaptive.get("lift") or 0.0)
    t093_stat_mult = float(adaptive.get("t093_stat_mult") or row.get("_t093_stat_mult") or 1.0)

    curve_cfg = target_progression_config(difficulty_cfg)
    use_curve = bool(curve_cfg.get("enabled")) and not t093_enabled(difficulty_cfg)
    model = str(row.get("model") or "")
    human_npc = is_human_npc_hp_model(model)

    if human_npc:
        hp_out = resolve_human_npc_table_hp(donor_row, difficulty)
        poise_out = resolve_adaptive_poise_out(
            donor_row,
            row=row,
            difficulty=difficulty,
            difficulty_cfg=difficulty_cfg,
            lift=lift,
            npc_by_id=npc_by_id,
        )
    elif use_curve:
        hp_out = resolve_assignment_hp_out(
            row,
            donor_row,
            difficulty=difficulty,
            npc_by_id=npc_by_id,
            difficulty_cfg=difficulty_cfg,
        )
        poise_out = resolve_target_curve_poise_out(
            donor_row,
            row=row,
            difficulty=difficulty,
            difficulty_cfg=difficulty_cfg,
        )
    else:
        hp_out = resolve_adaptive_hp_out(
            row,
            donor_row,
            difficulty=difficulty,
            npc_by_id=npc_by_id,
            difficulty_cfg=difficulty_cfg,
            lift=lift,
            donor_eff_hp=int(adaptive.get("donor_eff_hp") or 0),
            anchor_eff_hp=int(adaptive.get("anchor_eff_hp") or 0),
        )
        poise_out = resolve_adaptive_poise_out(
            donor_row,
            row=row,
            difficulty=difficulty,
            difficulty_cfg=difficulty_cfg,
            lift=lift,
            npc_by_id=npc_by_id,
        )

    sp_overrides = rebind_region_sp_effects(
        donor_row,
        slot_tier,
        difficulty_cfg,
        map_id=map_id,
        model=model,
    )
    attack = None
    t093_attack_mult = 1.0
    if not use_curve:
        if t093_enabled(difficulty_cfg):
            t093_attack_mult = compute_t093_attack_lift_mult(
                row,
                donor_row,
                difficulty=difficulty,
                npc_by_id=npc_by_id,
                difficulty_cfg=difficulty_cfg,
            )
        attack = resolve_adaptive_attack_sp(
            donor_row,
            row=row,
            lift=lift,
            occupied_slots=sp_overrides,
            difficulty_cfg=difficulty_cfg,
            t093_stat_mult=t093_stat_mult,
            difficulty=difficulty,
            npc_by_id=npc_by_id,
        )
    if attack:
        slot_key, sp_id = attack
        sp_overrides[slot_key] = sp_id

    baked_rune = int(row.get("rune_amount") or 0)
    if baked_rune > 0:
        soul_out = baked_rune
    elif soul_out <= 0:
        soul_out = max(0, int(row.get("_engine_soul") or 0))

    engine_hp = npc_base_hp(donor_row)
    engine_poise = npc_base_def_flick(donor_row)
    needs_hp = hp_out != engine_hp and hp_out > 0
    needs_poise = poise_out != engine_poise and poise_out > 0
    needs_sp = bool(sp_overrides)
    engine_soul = int(row.get("_engine_soul") or 0)
    needs_soul = soul_out > engine_soul and soul_out > 0
    needs_t093 = t093_enabled(difficulty_cfg) and (
        abs(t093_stat_mult - 1.0) > 1e-9 or needs_hp or needs_poise
    )
    needs_adaptive = (lift > 0 and (needs_hp or needs_poise or attack is not None)) or needs_t093

    if not (needs_hp or needs_poise or needs_sp or needs_soul or needs_adaptive):
        return None

    patch: dict[str, Any] = {
        "get_soul": soul_out,
        "slot_tier": slot_tier,
        "slot_map_id": map_id,
        "map_align_scale": round(applied_scale, 4),
        "user_mult": float(difficulty.get("user_mult", 1.0)),
    }
    if use_curve:
        patch["target_curve"] = True
    if adaptive.get("enabled") and not use_curve:
        patch["adaptive_lift"] = lift
        patch["donor_eff_hp"] = int(adaptive.get("donor_eff_hp") or 0)
        patch["anchor_eff_hp"] = int(adaptive.get("anchor_eff_hp") or 0)
        if adaptive.get("t093"):
            patch["t093_stat_mult"] = t093_stat_mult
            patch["t093_attack_mult"] = round(t093_attack_mult, 4)
    if needs_hp or (lift > 0 and hp_out > 0) or (use_curve and hp_out > 0) or (
        t093_enabled(difficulty_cfg) and hp_out > 0
    ):
        patch["hp"] = hp_out
    if needs_poise or (lift > 0 and poise_out > 0) or (use_curve and poise_out > 0) or (
        t093_enabled(difficulty_cfg) and poise_out > 0 and abs(t093_stat_mult - 1.0) > 1e-9
    ):
        patch["defFlickPower"] = poise_out
    if sp_overrides:
        patch["sp_effect_overrides"] = {
            str(k): int(v) for k, v in sorted(sp_overrides.items())
        }
    if attack:
        patch["attack_sp"] = {"slot": attack[0], "id": attack[1]}
    return patch


def patch_fingerprint(base_npc: int, patch: dict[str, Any]) -> str:
    payload = json.dumps(
        {"base_npc": base_npc, **patch},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


# Back-compat for npc_hp_floor imports
def assignment_hp_override(
    row: dict[str, Any],
    npc_by_id: dict[int, dict[str, str]],
) -> int | None:
    return boss_slot_hp_floor(
        src_cat=str(row.get("src_cat") or ""),
        src_npc=int(row.get("src_npc") or 0),
        donor_npc=int(row.get("npc") or 0),
        map_id=str(row.get("map_id") or ""),
        npc_by_id=npc_by_id,
    )
