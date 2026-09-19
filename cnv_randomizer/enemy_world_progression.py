"""T-093/T-094: map → world region → tier + map/journey mult + layer lift."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
DEFAULT_WORLD_REGIONS_PATH = SCRIPT_DIR / "enemy_world_regions.json"
DEFAULT_REGION_PROGRESSION_PATH = SCRIPT_DIR / "enemy_region_progression.json"
DEFAULT_MAP_REGIONS_PATH = SCRIPT_DIR / "enemy_map_regions.json"


@lru_cache(maxsize=1)
def load_world_regions(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_WORLD_REGIONS_PATH
    if not p.is_file():
        return {"regions": {}}
    return json.loads(p.read_text(encoding="utf-8-sig"))


@lru_cache(maxsize=1)
def load_region_progression(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_REGION_PROGRESSION_PATH
    if not p.is_file():
        return {"map_mult_by_tier": {"1": 1.0}}
    return json.loads(p.read_text(encoding="utf-8-sig"))


@lru_cache(maxsize=1)
def load_map_regions(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_MAP_REGIONS_PATH
    if not p.is_file():
        return {"by_map_id": {}, "default_region": "limgrave"}
    return json.loads(p.read_text(encoding="utf-8-sig"))


def region_meta(region_id: str, world: dict[str, Any] | None = None) -> dict[str, Any]:
    world = world or load_world_regions()
    regions = world.get("regions") or {}
    return dict(regions.get(str(region_id), {}))


def resolve_map_region_id(
    map_id: str,
    *,
    map_regions: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return (region_id, reason)."""
    mr = map_regions or load_map_regions()
    by_map = mr.get("by_map_id") or {}
    mid = str(map_id)
    if mid in by_map:
        entry = by_map[mid]
        if isinstance(entry, dict):
            return str(entry.get("region_id", entry.get("region", "limgrave"))), str(
                entry.get("reason", "field")
            )
        return str(entry), "field"
    default = str(mr.get("default_region") or "limgrave")
    return default, "default"


def resolve_region_tier(
    region_id: str,
    *,
    world: dict[str, Any] | None = None,
) -> int:
    meta = region_meta(region_id, world)
    try:
        return max(1, min(25, int(meta.get("tier", 1))))
    except (TypeError, ValueError):
        return 1


def resolve_map_tier_t093(
    map_id: str,
    *,
    map_regions: dict[str, Any] | None = None,
    world: dict[str, Any] | None = None,
) -> int:
    region_id, _ = resolve_map_region_id(map_id, map_regions=map_regions)
    return resolve_region_tier(region_id, world=world)


def region_map_mult(
    region_id: str,
    *,
    progression: dict[str, Any] | None = None,
    world: dict[str, Any] | None = None,
) -> float:
    progression = progression or load_region_progression()
    world = world or load_world_regions()
    overrides = progression.get("region_overrides") or {}
    if region_id in overrides and "map_mult" in overrides[region_id]:
        try:
            return max(0.01, float(overrides[region_id]["map_mult"]))
        except (TypeError, ValueError):
            pass
    tier = resolve_region_tier(region_id, world=world)
    table = progression.get("map_mult_by_tier") or {"1": 1.0}
    try:
        return max(0.01, float(table.get(str(tier), table.get("1", 1.0))))
    except (TypeError, ValueError):
        return 1.0


def resolve_map_mult_t093(
    map_id: str,
    *,
    map_regions: dict[str, Any] | None = None,
    progression: dict[str, Any] | None = None,
    world: dict[str, Any] | None = None,
) -> float:
    region_id, _ = resolve_map_region_id(map_id, map_regions=map_regions)
    return region_map_mult(region_id, progression=progression, world=world)


def is_underground_region(
    region_id: str,
    *,
    world: dict[str, Any] | None = None,
) -> bool:
    return bool(region_meta(region_id, world).get("underground", False))


def is_underground_map(
    map_id: str,
    *,
    map_regions: dict[str, Any] | None = None,
    world: dict[str, Any] | None = None,
) -> bool:
    region_id, _ = resolve_map_region_id(map_id, map_regions=map_regions)
    return is_underground_region(region_id, world=world)


def compute_slider_lift_mult(
    effective_hp: float,
    user_mult: float,
    *,
    h_ref: float,
    alpha: float = 0.5,
) -> float:
    """T-093 F20：s=1 不变；s>1 低血加得多；s<1 高血降得多。"""
    h = max(1.0, float(effective_hp))
    s = float(user_mult)
    if abs(s - 1.0) < 1e-9:
        return 1.0
    ref = max(1.0, float(h_ref))
    a = max(0.01, min(2.0, float(alpha)))
    if s > 1.0:
        exp = (ref / h) ** a
        return s**exp
    exp = (h / ref) ** a
    return s**exp


def asymmetric_layer_lift_mult(
    effective_hp: float,
    nominal_mult: float,
    *,
    h_ref: float,
    alpha: float = 0.5,
) -> float:
    """T-094 层 lift：名义>=1 时低血可高于名义，高血不低于名义。"""
    nom = float(nominal_mult)
    if abs(nom - 1.0) < 1e-9:
        return 1.0
    raw = compute_slider_lift_mult(
        effective_hp, nom, h_ref=h_ref, alpha=alpha
    )
    if nom >= 1.0:
        return max(nom, raw)
    return min(nom, raw)


def resolve_bracket_cap_mult(
    whitelist_hp: float,
    *,
    kind: str = "hp",
    difficulty_cfg: dict[str, Any] | None = None,
) -> float:
    """T-095/T-096：按白名单血量档返回血/属性/攻硬帽倍率。"""
    t094 = t094_config(difficulty_cfg)
    cap_key = {
        "hp": "hp_cap_mult",
        "stat": "stat_cap_mult",
        "attack": "attack_cap_mult",
    }.get(kind, "stat_cap_mult")
    default_fallback = {"hp": 3.0, "stat": 2.0, "attack": 1.45}.get(kind, 2.0)
    default = float(t094.get(cap_key, default_fallback))
    hp = max(1.0, float(whitelist_hp))
    brackets = list(t094.get("low_hp_brackets") or [])
    brackets.sort(key=lambda b: float(b.get("max_whitelist") or 0))
    for br in brackets:
        try:
            ceiling = float(br.get("max_whitelist") or 0)
        except (TypeError, ValueError):
            continue
        if ceiling <= 0:
            continue
        if hp <= ceiling + 1e-9:
            try:
                return max(1.0, float(br.get(cap_key, default)))
            except (TypeError, ValueError):
                return default
    return default


def map_layer_lift_mult(
    effective_hp: float,
    nominal_mult: float,
    *,
    difficulty_cfg: dict[str, Any] | None = None,
) -> float:
    """T-095 地图层 lift：独立 h_ref/alpha，低血可高于名义。"""
    t094 = t094_config(difficulty_cfg)
    h_ref = float(t094.get("map_layer_lift_h_ref", t094.get("layer_lift_h_ref", 2500.0)))
    alpha = float(t094.get("map_layer_lift_alpha", t094.get("layer_lift_alpha", 0.5)))
    return asymmetric_layer_lift_mult(
        effective_hp, nominal_mult, h_ref=h_ref, alpha=alpha
    )


def linear_tier_mult(lo: float, hi: float, index: int, index_max: int) -> float:
    idx = max(1, min(int(index_max), int(index)))
    n = max(1, int(index_max))
    if n <= 1:
        return float(lo)
    return float(lo) + (float(hi) - float(lo)) * (idx - 1) / (n - 1)


def t093_config(difficulty_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    if difficulty_cfg is None:
        return _t093_config_default()
    return _t093_config_impl(difficulty_cfg)


@lru_cache(maxsize=1)
def _t093_config_default() -> dict[str, Any]:
    from enemy_difficulty import load_difficulty_cfg

    return _t093_config_impl(load_difficulty_cfg())


def _t093_config_impl(difficulty_cfg: dict[str, Any]) -> dict[str, Any]:
    raw = dict(difficulty_cfg.get("t093_progression") or {})
    defaults: dict[str, Any] = {
        "enabled": True,
        "night_mult": 1.5,
        "lift_alpha": 0.5,
        "lift_h_ref": 2500.0,
        "clear_j1_region_sp": True,
        "user_mult_min": 0.01,
        "user_mult_max": 999.0,
    }
    out = {**defaults, **raw}
    out["enabled"] = bool(out.get("enabled", True))
    try:
        out["night_mult"] = max(1.0, float(out.get("night_mult", 1.5)))
    except (TypeError, ValueError):
        out["night_mult"] = 1.5
    try:
        out["lift_alpha"] = max(0.01, min(2.0, float(out.get("lift_alpha", 0.5))))
    except (TypeError, ValueError):
        out["lift_alpha"] = 0.5
    try:
        out["lift_h_ref"] = max(100.0, float(out.get("lift_h_ref", 2500.0)))
    except (TypeError, ValueError):
        out["lift_h_ref"] = 2500.0
    out["clear_j1_region_sp"] = bool(out.get("clear_j1_region_sp", True))
    return out


def t094_config(difficulty_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    from enemy_difficulty import load_difficulty_cfg

    cfg = load_difficulty_cfg() if difficulty_cfg is None else difficulty_cfg
    raw = dict(cfg.get("t094_caps") or {})
    defaults: dict[str, Any] = {
        "enabled": True,
        "hp_cap_mult": 3.0,
        "stat_cap_mult": 2.0,
        "map_hp_max": 1.5,
        "journey_hp_max": 2.0,
        "map_stat_max": 1.25,
        "map_atk_max": 1.25,
        "journey_stat_max": 1.6,
        "journey_atk_max": 1.45,
        "attack_cap_mult": 1.45,
        "journey_tiers": 9,
        "map_tiers": 25,
        "assumed_ng_region_sp_mult": 1.1,
        "layer_lift_alpha": 0.5,
        "layer_lift_h_ref": 2500.0,
        "map_layer_lift_alpha": 0.82,
        "map_layer_lift_h_ref": 4000.0,
        "weak_hp_cap_threshold": 5000,
        "weak_low_hp_attack_sp": True,
        "weak_attack_sp_min_boost": 0.05,
        "low_hp_brackets": [],
        "disable_map_attack_sp": False,
        "journey_hp_by_tier": {},
        "journey_stat_by_tier": {},
        "journey_atk_by_tier": {},
    }
    out = {**defaults, **raw}
    out["enabled"] = bool(out.get("enabled", True))
    for key, lo in (
        ("hp_cap_mult", 1.0),
        ("stat_cap_mult", 1.0),
        ("map_hp_max", 1.0),
        ("journey_hp_max", 1.0),
        ("map_stat_max", 1.0),
        ("map_atk_max", 1.0),
        ("journey_stat_max", 1.0),
        ("journey_atk_max", 1.0),
        ("attack_cap_mult", 1.0),
        ("assumed_ng_region_sp_mult", 1.0),
        ("layer_lift_alpha", 0.01),
        ("layer_lift_h_ref", 100.0),
    ):
        try:
            out[key] = max(lo, float(out.get(key, defaults[key])))
        except (TypeError, ValueError):
            out[key] = float(defaults[key])
    try:
        out["journey_tiers"] = max(1, int(out.get("journey_tiers", 9)))
    except (TypeError, ValueError):
        out["journey_tiers"] = 9
    try:
        out["map_tiers"] = max(1, int(out.get("map_tiers", 25)))
    except (TypeError, ValueError):
        out["map_tiers"] = 25
    out["disable_map_attack_sp"] = bool(out.get("disable_map_attack_sp", False))
    try:
        out["weak_hp_cap_threshold"] = max(
            1.0, float(out.get("weak_hp_cap_threshold", 5000))
        )
    except (TypeError, ValueError):
        out["weak_hp_cap_threshold"] = 5000.0
    out["weak_low_hp_attack_sp"] = bool(out.get("weak_low_hp_attack_sp", True))
    try:
        out["weak_attack_sp_min_boost"] = max(
            0.0, float(out.get("weak_attack_sp_min_boost", 0.05))
        )
    except (TypeError, ValueError):
        out["weak_attack_sp_min_boost"] = 0.05
    try:
        out["map_layer_lift_alpha"] = max(
            0.01, float(out.get("map_layer_lift_alpha", out["layer_lift_alpha"]))
        )
    except (TypeError, ValueError):
        out["map_layer_lift_alpha"] = float(out["layer_lift_alpha"])
    try:
        out["map_layer_lift_h_ref"] = max(
            100.0, float(out.get("map_layer_lift_h_ref", out["layer_lift_h_ref"]))
        )
    except (TypeError, ValueError):
        out["map_layer_lift_h_ref"] = float(out["layer_lift_h_ref"])
    raw_brackets = out.get("low_hp_brackets")
    if not isinstance(raw_brackets, list):
        out["low_hp_brackets"] = []
    return out


def t093_enabled(difficulty_cfg: dict[str, Any] | None = None) -> bool:
    """Partial test cfgs without ``t093_progression`` stay on legacy lift path."""
    if difficulty_cfg is not None and "t093_progression" not in difficulty_cfg:
        return False
    return bool(t093_config(difficulty_cfg).get("enabled", False))


def t094_enabled(difficulty_cfg: dict[str, Any] | None = None) -> bool:
    if not t093_enabled(difficulty_cfg):
        return False
    if difficulty_cfg is not None and "t094_caps" not in difficulty_cfg:
        # live cfg always has t094 when loaded from json; partial tests without key skip
        return False
    return bool(t094_config(difficulty_cfg).get("enabled", False))


def _table_mult(table: dict[str, Any] | None, index: int, fallback: float) -> float:
    if not table:
        return float(fallback)
    try:
        return max(0.01, float(table.get(str(index), fallback)))
    except (TypeError, ValueError):
        return float(fallback)


def nominal_map_hp_mult(
    map_tier: int,
    *,
    difficulty_cfg: dict[str, Any] | None = None,
    progression: dict[str, Any] | None = None,
) -> float:
    progression = progression or load_region_progression()
    table = progression.get("map_mult_by_tier") or {}
    t094 = t094_config(difficulty_cfg)
    if str(map_tier) in table:
        return _table_mult(table, map_tier, 1.0)
    return linear_tier_mult(
        1.0, float(t094.get("map_hp_max", 1.5)), map_tier, int(t094.get("map_tiers", 25))
    )


def nominal_map_stat_mult(
    map_tier: int,
    *,
    difficulty_cfg: dict[str, Any] | None = None,
    progression: dict[str, Any] | None = None,
) -> float:
    progression = progression or load_region_progression()
    table = progression.get("map_stat_mult_by_tier") or {}
    t094 = t094_config(difficulty_cfg)
    if str(map_tier) in table:
        return _table_mult(table, map_tier, 1.0)
    return linear_tier_mult(1.0, float(t094["map_stat_max"]), map_tier, int(t094["map_tiers"]))


def nominal_map_atk_mult(
    map_tier: int,
    *,
    difficulty_cfg: dict[str, Any] | None = None,
    progression: dict[str, Any] | None = None,
) -> float:
    """T-096：地图攻名义倍率，档 1→25 线性 1.0→map_atk_max。"""
    progression = progression or load_region_progression()
    table = progression.get("map_atk_mult_by_tier") or {}
    t094 = t094_config(difficulty_cfg)
    if str(map_tier) in table:
        return _table_mult(table, map_tier, 1.0)
    return linear_tier_mult(1.0, float(t094["map_atk_max"]), map_tier, int(t094["map_tiers"]))


def nominal_journey_hp_mult(
    journey_tier: int,
    *,
    difficulty_cfg: dict[str, Any] | None = None,
) -> float:
    t094 = t094_config(difficulty_cfg)
    table = t094.get("journey_hp_by_tier") or {}
    j = max(1, min(int(t094["journey_tiers"]), int(journey_tier)))
    if str(j) in table:
        return _table_mult(table, j, 1.0)
    return linear_tier_mult(1.0, float(t094["journey_hp_max"]), j, int(t094["journey_tiers"]))


def nominal_journey_stat_mult(
    journey_tier: int,
    *,
    difficulty_cfg: dict[str, Any] | None = None,
) -> float:
    t094 = t094_config(difficulty_cfg)
    table = t094.get("journey_stat_by_tier") or {}
    j = max(1, min(int(t094["journey_tiers"]), int(journey_tier)))
    if str(j) in table:
        return _table_mult(table, j, 1.0)
    return linear_tier_mult(1.0, float(t094["journey_stat_max"]), j, int(t094["journey_tiers"]))


def nominal_journey_atk_mult(
    journey_tier: int,
    *,
    difficulty_cfg: dict[str, Any] | None = None,
) -> float:
    t094 = t094_config(difficulty_cfg)
    table = t094.get("journey_atk_by_tier") or {}
    j = max(1, min(int(t094["journey_tiers"]), int(journey_tier)))
    if str(j) in table:
        return _table_mult(table, j, 1.0)
    return linear_tier_mult(1.0, float(t094["journey_atk_max"]), j, int(t094["journey_tiers"]))


def resolve_journey_tier(difficulty: dict[str, Any] | None = None) -> int:
    """1..9；默认一周目=1。可用 journey_tier 或 ng_cycle(0..7→2..8，0→1)。"""
    d = difficulty or {}
    if "journey_tier" in d:
        try:
            return max(1, min(9, int(d.get("journey_tier", 1))))
        except (TypeError, ValueError):
            return 1
    if "ng_cycle" in d:
        try:
            ng = max(0, min(7, int(d.get("ng_cycle", 0))))
            return ng + 1  # ClearCount0=周目1
        except (TypeError, ValueError):
            return 1
    return 1


def night_mult_for_row(
    row: dict[str, Any],
    map_id: str,
    *,
    difficulty_cfg: dict[str, Any] | None = None,
) -> float:
    cfg = t093_config(difficulty_cfg)
    tgt = str(row.get("tgt_cat") or "")
    if tgt != "night":
        return 1.0
    if is_underground_map(map_id):
        return 1.0
    return float(cfg["night_mult"])


def ng_mult_journey0(difficulty_cfg: dict[str, Any] | None = None) -> float:
    return 1.0


def scale_int_ceil(base: int, mult: float) -> int:
    if base <= 0:
        return base
    return max(1, int(math.ceil(base * mult)))
