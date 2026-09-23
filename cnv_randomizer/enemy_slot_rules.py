"""Slot skip / decorative / policy rules (extracted from enemy_randomizer_core)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from boss_npc_detect import is_script_event_npc_slot, is_talk_npc_id, resolve_entity_category
from enemy_category_rules import (
    _model_has_prefix,
    is_caravan_event_slot,
    is_cnv_original_boss_slot_npc_id,
    is_excluded_slot_model,
    is_excluded_slot_npc_id,
    is_invisible_enemy_model,
    is_keep_original_map_entity_slot,
    is_keep_original_slot_model,
    is_non_participating_map,
    is_passive_animal_model,
    is_scripted_dungeon_main_boss_slot,
    is_siege_c1000_operator_slot,
    is_siege_mount_rider_slot,
    is_siege_operator_slot,
    resolve_size_tier,
    resolve_src_category,
    should_skip_excluded_slot_tier,
)
from enemy_mount_pairs import CNV_SUPPRESS_DECORATIVE_TEMPLATE
from paths import GAME_DIR, SCRIPT_DIR

DEFAULT_CATEGORIES_PATH = SCRIPT_DIR / "enemy_categories.json"

_PREP_REVALIDATE_SKIP_KEYS = frozenset({"npc", "hub", "siege"})


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def is_decorative_npc_slot(slot: dict[str, Any], categories_cfg: dict[str, Any]) -> bool:
    """地图装饰/NPC 灵体槽（npc==think）：不参与随机。"""
    try:
        npc = int(slot.get("npc", 0))
        think = int(slot.get("think", 0))
    except (TypeError, ValueError):
        return False
    below = int(categories_cfg.get("exclude_donor_npc_equals_think_below", 0) or 0)
    return npc == think and 0 < npc < below


def slot_has_walk_route(slot: dict[str, Any]) -> bool:
    """MSB 巡逻路非空（含日文巡回名 / walk_route_* id）。"""
    return bool(str(slot.get("walk_route") or "").strip())


def is_decorative_suppress_slot(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
    npc_csv_dir: str | Path | None = None,
) -> bool:
    """装饰槽：不随机，且 apply 时沉底剔除（不进场站桩）。

    c3661/c3662/c4711 腐败遗体走 keep_original，保留原版 MSB，不沉底（2026-08-14：
    沉底会把露台等地尸堆/慢走咬人活尸整片弄没）。

    有 walk_route 的 c0100 系 / npc==think 假人 = 巡逻领队，不沉底（2026-08-20：
    门前蝙蝠群领队沉底后跟随怪不飞巡）。

    巨人马车事件图上 c0110/c0100 领队假人不沉底（2026-09-09：沉底→铁链连空气）。
    """
    if slot_has_walk_route(slot):
        return False
    map_id = str(slot.get("map_id") or "")
    event_maps = {
        str(x) for x in (categories_cfg.get("cnv_caravan_event_maps") or [])
    }
    if map_id in event_maps:
        slot_model = str(slot.get("model") or "").lower()
        entity = str(slot.get("name") or slot.get("entity_name") or "").lower()
        if slot_model.startswith(("c0110", "c0100")) or any(
            marker in entity
            for marker in ("-c0110_", "c0110_", "-c0100_", "c0100_")
        ):
            return False
    slot_model = str(slot.get("model", ""))
    if _model_has_prefix(
        slot_model, categories_cfg.get("decorative_slot_model_prefixes") or []
    ):
        return True
    if is_decorative_npc_slot(slot, categories_cfg):
        return True
    return False


def build_decorative_suppress_assignments(
    index: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    map_filter: str | None = None,
    occupied_keys: set[tuple[str, str]] | None = None,
    npc_csv_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """为全图装饰槽生成 apply 沉底行（spawn 表未覆盖的槽）。"""
    occupied = occupied_keys or set()
    out: list[dict[str, Any]] = []
    for slot in index.get("slots", []):
        map_id = str(slot.get("map_id", ""))
        entity_name = str(slot.get("name", ""))
        if not map_id or not entity_name:
            continue
        if map_filter and map_id != map_filter:
            continue
        key = (map_id, entity_name)
        if key in occupied:
            continue
        if not is_decorative_suppress_slot(slot, categories_cfg, npc_csv_dir):
            continue
        out.append(
            {
                "map_id": map_id,
                "entity_name": entity_name,
                "src_cat": str(slot.get("src_cat") or "trash"),
                "tgt_cat": "decorative",
                "template_id": CNV_SUPPRESS_DECORATIVE_TEMPLATE,
                "donor_map": "",
                "donor_entity": "",
                "model": str(slot.get("model") or "decorative"),
                "npc": 0,
                "think": 0,
                "chara": -1,
                "rune_amount": 0,
                "archetype_id": "decorative",
                "archetype_zh": "装饰剔除",
                "suppress_decorative": True,
            }
        )
    return out


def augment_spawn_map_path_with_decorative_suppress(
    spawn_map_path: Path,
    *,
    map_filter: str | None = None,
    npc_csv_dir: str | Path | None = None,
) -> Path:
    """apply 兜底：在 spawn 表末尾追加装饰沉底行（临时文件）。"""
    from enemy_randomizer_core import load_enemy_index, load_npc_soul_map

    categories_cfg = _load_json(DEFAULT_CATEGORIES_PATH)
    index = load_enemy_index()
    text = spawn_map_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    occupied: set[tuple[str, str]] = set()
    for ln in lines:
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("seed=") or ln.startswith("mob_drop") or ln.startswith("difficulty"):
            continue
        if ln.startswith("slots=") or ln.startswith("npc_"):
            continue
        parts = ln.split("\t")
        if len(parts) >= 2:
            occupied.add((parts[0], parts[1]))
    extra = build_decorative_suppress_assignments(
        index,
        categories_cfg,
        map_filter=map_filter,
        occupied_keys=occupied,
        npc_csv_dir=npc_csv_dir,
    )
    if not extra:
        return spawn_map_path
    soul_map = load_npc_soul_map()
    extra_lines = [
        _assignment_to_spawn_line(row, soul_map)
        for row in sorted(extra, key=lambda r: (r["map_id"], r["entity_name"]))
    ]
    out_path = spawn_map_path.with_name(f"{spawn_map_path.stem}_decor.augmented.txt")
    slot_count = sum(
        1
        for ln in lines
        if ln
        and not ln.startswith("#")
        and not ln.startswith("seed=")
        and not ln.startswith("mob_drop")
        and not ln.startswith("difficulty")
        and not ln.startswith("slots=")
        and not ln.startswith("npc_")
        and "\t" in ln
    )
    slot_count += len(extra_lines)
    out_lines: list[str] = []
    slots_updated = False
    for ln in lines:
        if ln.startswith("slots=") and not slots_updated:
            out_lines.append(f"slots={slot_count}")
            slots_updated = True
            continue
        out_lines.append(ln)
    if not slots_updated:
        out_lines.append(f"slots={slot_count}")
    out_lines.extend(extra_lines)
    out_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return out_path


def _assignment_to_spawn_line(row: dict[str, Any], soul_map: dict[int, int]) -> str:
    npc_runtime = int(row["npc"])
    npc_donor = int(row.get("npc_donor") or npc_runtime)
    rune_amount = int(row["rune_amount"])
    engine_soul = int(soul_map.get(npc_donor, 0) or 0)
    if engine_soul < 0:
        engine_soul = 0
    rune_delta = max(0, rune_amount - engine_soul)
    return "\t".join(
        [
            str(row["map_id"]),
            str(row["entity_name"]),
            str(row["src_cat"]),
            str(row["tgt_cat"]),
            str(row["template_id"]),
            str(row["model"]),
            str(npc_runtime),
            str(row["think"]),
            str(row["chara"]),
            str(rune_amount),
            str(engine_soul),
            str(rune_delta),
            str(npc_donor),
        ]
    )


def is_talk_npc_slot(
    slot: dict[str, Any],
    csv_dir: str | Path | None = None,
) -> bool:
    """剧情/可对话 NPC（NpcParam 命名 + 无卢恩掉落）— 槽位不参与随机。"""
    try:
        npc = int(slot.get("npc", 0))
    except (TypeError, ValueError):
        return False
    if npc <= 0:
        return False
    base = Path(csv_dir) if csv_dir else (GAME_DIR / "csv")
    return is_talk_npc_id(npc, base)


def is_msb_talk_slot(slot: dict[str, Any]) -> bool:
    """MSB 槽位绑定了 TalkID（对话菜单）— 剧情 NPC，不参与随机。"""
    for key in ("talk_id", "talkId"):
        try:
            talk = int(slot.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if talk > 0:
            return True
    return False


def runtime_slot_skip_after_prep(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> str | None:
    """Prep 未冻结的规则：大赐福 / keep_original / 排除槽 / 攻城操作员。"""
    map_id = str(slot.get("map_id", ""))
    slot_model = str(slot.get("model", ""))
    if is_non_participating_map(map_id, categories_cfg):
        return "npc"
    if is_keep_original_map_entity_slot(slot, categories_cfg):
        return "npc"
    if is_excluded_slot_npc_id(slot, categories_cfg):
        return "npc"
    if is_cnv_original_boss_slot_npc_id(slot, categories_cfg):
        return "npc"
    if is_keep_original_slot_model(slot_model, categories_cfg):
        return "scarab"
    if is_excluded_slot_model(slot_model, categories_cfg, slot, GAME_DIR / "csv"):
        return "npc"
    if is_siege_operator_slot(slot, categories_cfg):
        return "npc"
    return None


def runtime_slot_skip_bucket(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    npc_csv_dir: str | Path | None = None,
    size_map: dict[str, Any] | None = None,
) -> str | None:
    """生成时实时判定跳过（不依赖 slot_prep 是否过期）。返回 skip_counts 用的桶名。"""
    map_id = str(slot.get("map_id", ""))
    slot_model = str(slot.get("model", ""))
    if is_non_participating_map(map_id, categories_cfg):
        return "npc"
    if is_keep_original_map_entity_slot(slot, categories_cfg):
        return "npc"
    if is_excluded_slot_npc_id(slot, categories_cfg):
        return "npc"
    if is_cnv_original_boss_slot_npc_id(slot, categories_cfg):
        return "npc"
    # 雾门主线 _9000：MSB 常挂过场 talk_id，体型又是 boss，旧规则整槽不洗（葛瑞克还是葛瑞克）。
    # 满月/圣特里娜等 exclude_slot 模型仍原位。
    if is_scripted_dungeon_main_boss_slot(slot, categories_cfg) and not is_excluded_slot_model(
        slot_model, categories_cfg, slot, Path(npc_csv_dir) if npc_csv_dir else (GAME_DIR / "csv")
    ):
        return None
    if is_talk_npc_slot(slot, npc_csv_dir):
        return "npc"
    if is_msb_talk_slot(slot):
        return "npc"
    base = Path(npc_csv_dir) if npc_csv_dir else (GAME_DIR / "csv")
    if is_script_event_npc_slot(slot, base, categories_cfg):
        return "npc"
    if is_caravan_event_slot(slot, categories_cfg):
        return "npc"
    if is_excluded_slot_model(slot_model, categories_cfg, slot, base):
        return "npc"
    if is_siege_operator_slot(slot, categories_cfg):
        return "npc"
    if is_invisible_enemy_model(slot_model, categories_cfg):
        return "npc"
    if is_decorative_npc_slot(slot, categories_cfg):
        return "npc"
    if is_passive_animal_model(slot_model, categories_cfg):
        return "animal"
    if is_keep_original_slot_model(slot_model, categories_cfg):
        return "scarab"
    tier_map = size_map if size_map is not None else categories_cfg.get(
        "size_tier_by_model_prefix", {}
    )
    exclude_slot_tiers = set(categories_cfg.get("exclude_slot_size_tiers") or [])
    slot_tier = resolve_size_tier(slot_model, tier_map)
    if should_skip_excluded_slot_tier(slot_tier, exclude_slot_tiers):
        return "large"
    return None


_PREP_REVALIDATE_SKIP_KEYS = frozenset({"npc", "hub", "siege"})


def revalidate_prep_skip_key(
    skip_key: str | None,
    slot: dict[str, Any] | None,
    *,
    categories_cfg: dict[str, Any],
    npc_csv_dir: str | Path | None = None,
) -> str | None:
    """Prep 里冻住的 npc/hub/siege 跳过，生成时用当前 categories 再判一次。

    避免改跳过规则（如攻城操作员）后只重随机、不重建槽位缓存仍读旧 k 字段。
    """
    if not skip_key or skip_key not in _PREP_REVALIDATE_SKIP_KEYS:
        return skip_key
    if slot is None:
        return skip_key
    result = runtime_slot_skip_bucket(
        slot, categories_cfg, npc_csv_dir=npc_csv_dir
    )
    if skip_key == "npc" and not result:
        if is_scripted_dungeon_main_boss_slot(slot, categories_cfg):
            slot_model = str(slot.get("model", ""))
            if not is_excluded_slot_model(slot_model, categories_cfg, slot, npc_csv_dir):
                return None
        if (
            is_msb_talk_slot(slot)
            or is_excluded_slot_npc_id(slot, categories_cfg)
            or is_cnv_original_boss_slot_npc_id(slot, categories_cfg)
        ):
            return "npc"
        slot_model = str(slot.get("model", ""))
        if is_excluded_slot_model(slot_model, categories_cfg, slot, npc_csv_dir):
            return "npc"
    return result


def resolve_effective_slot_skip(
    prep_skip_key: str | None,
    slot: dict[str, Any] | None,
    *,
    categories_cfg: dict[str, Any],
    npc_csv_dir: str | Path | None = None,
) -> str | None:
    """合并 prep 冻结跳过与实时规则（底表 / 生成共用）。

    旧 prep 无 k 或缺 script_event 等规则时，仍靠 runtime_slot_skip_bucket 兜底。
    """
    if prep_skip_key == "mount":
        return "mount"
    skip_key = prep_skip_key
    if skip_key in _PREP_REVALIDATE_SKIP_KEYS:
        skip_key = revalidate_prep_skip_key(
            skip_key,
            slot,
            categories_cfg=categories_cfg,
            npc_csv_dir=npc_csv_dir,
        )
    if skip_key:
        return str(skip_key)
    if slot is None:
        return None
    live = runtime_slot_skip_bucket(
        slot, categories_cfg, npc_csv_dir=npc_csv_dir
    )
    if live:
        return live
    return runtime_slot_skip_after_prep(slot, categories_cfg)


def _count_prep_skip_bucket(skip_key: str, skip_counts: dict[str, int]) -> None:
    if skip_key == "large":
        skip_counts["skipped_large"] += 1
    elif skip_key == "animal":
        skip_counts["skipped_passive_animal"] += 1
    elif skip_key in ("npc", "hub"):
        skip_counts["skipped_npc_slot"] += 1
    elif skip_key == "scarab":
        skip_counts["skipped_scarab"] += 1
    elif skip_key in ("medium_dungeon", "zone_restricted"):
        skip_counts["skipped"] += 1
    elif skip_key != "mount":
        skip_counts["skipped"] += 1


def _slot_placement_kind(slot: dict[str, Any]) -> str:
    model = str(slot.get("model", ""))
    backup = int(slot.get("backup_anim", -1) or -1)
    walk = str(slot.get("walk_route") or "").strip()
    collision = str(slot.get("collision_part") or "").strip()
    aerial_prefixes = (
        "c6001", "c4560", "c4561", "c4562", "c4563",
        "c4500", "c4501", "c4502", "c4503", "c4504", "c4505", "c4510", "c4511", "c4520",
    )
    if any(model.lower().startswith(p) for p in aerial_prefixes):
        return "aerial_model"
    if backup > 0 and not walk:
        return "perch_or_squat"
    if collision and not walk:
        return "collision_anchor"
    if walk:
        return "patrol"
    return "ground"


def _slot_apply_collision_policy(slot: dict[str, Any]) -> str:
    if _slot_placement_kind(slot) == "aerial_model":
        return "clear_on_apply"
    return "keep_on_apply"

def collect_slot_skip_rule_ids(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    npc_csv_dir: str | Path | None = None,
    size_map: dict[str, Any] | None = None,
) -> list[str]:
    """All skip rules that match this slot (engineering baseline; ordered)."""
    map_id = str(slot.get("map_id", ""))
    slot_model = str(slot.get("model", ""))
    base = Path(npc_csv_dir) if npc_csv_dir else (GAME_DIR / "csv")
    rules: list[str] = []
    if is_non_participating_map(map_id, categories_cfg):
        rules.append("hub_map")
    if is_keep_original_map_entity_slot(slot, categories_cfg):
        rules.append("keep_original_map_entity")
    if is_talk_npc_slot(slot, npc_csv_dir):
        rules.append("talk_npc")
    if is_msb_talk_slot(slot):
        rules.append("msb_talk")
    if is_script_event_npc_slot(slot, base, categories_cfg):
        rules.append("script_event")
    if is_caravan_event_slot(slot, categories_cfg):
        rules.append("caravan_event")
    if is_siege_mount_rider_slot(slot, categories_cfg):
        rules.append("siege_mount_rider")
    elif is_siege_c1000_operator_slot(slot, categories_cfg):
        rules.append("siege_operator")
    if is_excluded_slot_model(slot_model, categories_cfg, slot, base):
        rules.append("exclude_model")
    if is_invisible_enemy_model(slot_model, categories_cfg):
        rules.append("invisible")
    if is_decorative_npc_slot(slot, categories_cfg):
        rules.append("decorative_npc")
    if is_passive_animal_model(slot_model, categories_cfg):
        rules.append("passive_animal")
    if is_keep_original_slot_model(slot_model, categories_cfg):
        rules.append("keep_original")
    tier_map = size_map if size_map is not None else categories_cfg.get(
        "size_tier_by_model_prefix", {}
    )
    exclude_slot_tiers = set(categories_cfg.get("exclude_slot_size_tiers") or [])
    slot_tier = resolve_size_tier(slot_model, tier_map)
    if should_skip_excluded_slot_tier(slot_tier, exclude_slot_tiers):
        rules.append("large_tier")
    return rules


def describe_slot_policy(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    npc_csv_dir: str | Path | None = None,
    prep_row: dict[str, Any] | None = None,
    spawn_keys: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Canonical per-slot policy for baseline table + audits (single source of truth)."""
    from boss_npc_detect import is_talk_npc_row, load_npc_rows, row_has_dialogue_sp
    from enemy_randomizer_core import CATEGORY_NUM

    map_id = str(slot.get("map_id", ""))
    entity = str(slot.get("name", ""))
    model = str(slot.get("model", ""))
    base = Path(npc_csv_dir) if npc_csv_dir else (GAME_DIR / "csv")
    npc_rows = load_npc_rows(base)
    try:
        npc_id = int(slot.get("npc", 0) or 0)
    except (TypeError, ValueError):
        npc_id = 0
    npc_row = npc_rows.get(npc_id, {})
    try:
        think = int(slot.get("think", 0) or 0)
    except (TypeError, ValueError):
        think = 0

    rules_cat = resolve_src_category(model, categories_cfg)
    src_cat = resolve_entity_category(
        slot,
        categories_cfg=categories_cfg,
        csv_dir=base,
        rules_category=rules_cat,
    )
    rule_ids = collect_slot_skip_rule_ids(
        slot, categories_cfg, npc_csv_dir=base
    )
    prep_k = (prep_row or {}).get("k")
    effective_skip = resolve_effective_slot_skip(
        prep_k,
        slot,
        categories_cfg=categories_cfg,
        npc_csv_dir=base,
    )
    participate = effective_skip is None
    placement = _slot_placement_kind(slot)

    if not participate:
        if "talk_npc" in rule_ids or "msb_talk" in rule_ids:
            slot_role = "story_talk"
        elif "script_event" in rule_ids:
            slot_role = "story_event"
        elif "passive_animal" in rule_ids:
            slot_role = "ambient_animal"
        elif "keep_original" in rule_ids:
            slot_role = "keep_original"
        elif "hub_map" in rule_ids:
            slot_role = "hub"
        else:
            slot_role = "skip_other"
    elif placement == "perch_or_squat":
        slot_role = "combat_perch"
    elif placement == "aerial_model":
        slot_role = "combat_aerial"
    elif placement == "patrol":
        slot_role = "combat_patrol"
    elif placement == "collision_anchor":
        slot_role = "combat_ledge"
    else:
        slot_role = "combat_ground"

    policy = "participate" if participate else "skip"
    return {
        "map_id": map_id,
        "entity": entity,
        "model": model,
        "src_cat": src_cat,
        "src_pool": f"{CATEGORY_NUM.get(src_cat, '?')}_{src_cat}",
        "policy": policy,
        "slot_role": slot_role,
        "rule_ids": rule_ids,
        "effective_skip": effective_skip or "",
        "prep_skip_frozen": prep_k or "",
        "has_prep_donor_pools": bool((prep_row or {}).get("o")),
        "in_last_spawn_map": (map_id, entity) in (spawn_keys or set()),
        "placement": placement,
        "apply_collision": _slot_apply_collision_policy(slot),
        "npc": npc_id,
        "think": think,
        "npc_soul": int(npc_row.get("getSoul") or 0) if npc_row else None,
        "npc_name_id": int(npc_row.get("nameId") or 0) if npc_row else None,
        "npc_dialogue_sp": bool(row_has_dialogue_sp(npc_row)) if npc_row else False,
        "npc_talk_row": bool(is_talk_npc_row(npc_row)) if npc_row else False,
        "backup_anim": int(slot.get("backup_anim", -1) or -1),
        "walk_route": str(slot.get("walk_route") or ""),
        "collision_part": str(slot.get("collision_part") or ""),
        "map_kind": str((slot.get("slot_tags") or {}).get("map_kind", "")),
    }
