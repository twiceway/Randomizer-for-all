"""T-073 R3.2 — enemy pool filter helpers (extracted from enemy_randomizer_core).

Facade: ``from enemy_randomizer_core import filter_pool_for_*`` still works via re-export.
Helpers still living in enemy_randomizer_core are late-imported inside each function
to avoid circular imports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from boss_npc_detect import (
    is_dungeon_incompatible_field_trash_model,
    is_indoor_dungeon_boss_arena_exclude_donor,
    is_indoor_dungeon_boss_arena_slot,
    is_oversize_boss_model,
    is_red_spirit_model,
    should_downgrade_shared_model_to_trash,
    template_is_cnv_new_npc_red_spirit,
)
from donor_pool_review_allowlist import (
    is_allowlisted_donor_template,
)
from paths import GAME_DIR


def filter_pool_for_anchor_plant_slot(
    pool: list[dict[str, Any]],
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """植物锚点槽（c4481/c4483）：仅植物族捐皮。"""
    from enemy_category_rules import donor_blocked_for_anchor_plant_slot

    slot_model = str(slot.get("model", ""))
    out: list[dict[str, Any]] = []
    for tpl in pool:
        model = str(tpl.get("model", ""))
        if donor_blocked_for_anchor_plant_slot(slot_model, model, categories_cfg):
            continue
        out.append(tpl)
    return out


def filter_prep_donor_indices_for_anchor_plant(
    prep: dict[str, Any],
    indices: list[int],
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> list[int]:
    from enemy_category_rules import donor_blocked_for_anchor_plant_slot

    if not indices:
        return indices
    slot_model = str(slot.get("model", ""))
    donors = prep.get("donors") or []
    out: list[int] = []
    for i in indices:
        if i < 0 or i >= len(donors):
            continue
        model = str(donors[i].get("model", ""))
        if donor_blocked_for_anchor_plant_slot(slot_model, model, categories_cfg):
            continue
        out.append(i)
    return out


def filter_pool_for_narrow_placement(
    pool: list[dict[str, Any]],
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    size_map: dict[str, str] | None = None,
    tgt_cat: str = "",
) -> list[dict[str, Any]]:
    """体型辅助层：池已选定后，剔除会在狭窄处崩模的捐皮。"""
    from enemy_randomizer_core import (
        BOSS_TARGET_CATEGORIES,
        donor_blocked_for_narrow_placement,
        effective_slot_map_kind,
        is_scripted_dungeon_main_boss_slot,
        narrow_map_kinds,
        resolve_size_tier,
    )
    if is_scripted_dungeon_main_boss_slot(slot, categories_cfg):
        return pool
    map_id = str(slot.get("map_id", ""))
    entity_name = str(slot.get("name") or slot.get("entity") or "")
    tier_map = size_map or categories_cfg.get("size_tier_by_model_prefix", {})
    slot_tier = resolve_size_tier(str(slot.get("model", "")), tier_map)
    map_k = effective_slot_map_kind(slot, categories_cfg)
    boss_tgt = tgt_cat in BOSS_TARGET_CATEGORIES
    out: list[dict[str, Any]] = []
    for tpl in pool:
        model = str(tpl.get("model", ""))
        donor_tier = resolve_size_tier(model, tier_map)
        if donor_blocked_for_narrow_placement(
            donor_tier,
            slot_tier,
            map_id,
            categories_cfg,
            tgt_cat=tgt_cat,
            entity_name=entity_name,
            donor_model=model,
            slot=slot,
        ):
            continue
        if boss_tgt and map_k in narrow_map_kinds(categories_cfg):
            if is_dungeon_incompatible_field_trash_model(model, categories_cfg):
                continue
            if is_oversize_boss_model(model):
                continue
        out.append(tpl)
    return out


def filter_pool_for_scripted_fog_boss_donors(
    pool: list[dict[str, Any]],
    slot: dict[str, Any],
    tgt_cat: str,
    categories_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """与 filter_scripted_fog_boss_donor_indices 同口径，供 prep 建池。"""
    from enemy_category_rules import (
        _SCRIPTED_DUNGEON_BOSS_TGT,
        is_boss_pool_excluded_donor,
        is_scripted_dungeon_main_boss_slot,
    )
    if not is_scripted_dungeon_main_boss_slot(slot, categories_cfg):
        return pool
    if tgt_cat not in _SCRIPTED_DUNGEON_BOSS_TGT:
        return pool
    return [
        tpl
        for tpl in pool
        if str(tpl.get("template_id", "")).startswith("synthetic:")
        and not is_boss_pool_excluded_donor(tpl, categories_cfg)
    ]


def filter_pool_for_red_spirit_targets(
    pool: list[dict[str, Any]],
    tgt_cat: str,
    categories_cfg: dict[str, Any],
    *,
    csv_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """5 池红灵捐皮：red_spirit_model_prefixes + 法魂 ``New NPC #`` 原创红灵。"""
    if tgt_cat != "night":
        return pool
    base = Path(csv_dir) if csv_dir else (GAME_DIR / "csv")

    def _ok(t: dict[str, Any]) -> bool:
        if is_red_spirit_model(str(t.get("model", "")), categories_cfg):
            return True
        return template_is_cnv_new_npc_red_spirit(t, base)

    return [t for t in pool if _ok(t)]


def filter_pool_for_major_boss_named_targets(
    pool: list[dict[str, Any]],
    tgt_cat: str,
    categories_cfg: dict[str, Any],
    *,
    csv_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """7 池：法魂具名 Boss（绑定表 / ``[Boss]`` / ``[地名]`` / donor_origin=cnv 合成）。"""
    from enemy_randomizer_core import is_cnv_named_boss_donor_template
    if tgt_cat != "major_boss":
        return pool
    return [
        t
        for t in pool
        if is_cnv_named_boss_donor_template(t, categories_cfg, csv_dir=csv_dir)
    ]


def filter_pool_for_field_boss_targets(
    pool: list[dict[str, Any]],
    tgt_cat: str,
    categories_cfg: dict[str, Any],
    *,
    slot: dict[str, Any] | None = None,
    src_cat: str = "",
) -> list[dict[str, Any]]:
    """3 池（监牢+野外）：黑夜骑兵骑手/马分流；路边槽不装灵马。"""
    from enemy_randomizer_core import (
        is_field_cavalry_mount_model,
        is_field_cavalry_rider_model,
    )
    if tgt_cat != "evergaol":
        return pool
    if not slot:
        return pool
    slot_model = str(slot.get("model", ""))
    if is_field_cavalry_mount_model(slot_model, categories_cfg):
        return [
            t
            for t in pool
            if is_field_cavalry_mount_model(str(t.get("model", "")), categories_cfg)
        ]
    if is_field_cavalry_rider_model(slot_model, categories_cfg):
        return [
            t
            for t in pool
            if is_field_cavalry_rider_model(str(t.get("model", "")), categories_cfg)
        ]
    return [
        t
        for t in pool
        if not is_field_cavalry_mount_model(str(t.get("model", "")), categories_cfg)
    ]


def filter_pool_for_night_targets(
    pool: list[dict[str, Any]],
    tgt_cat: str,
    categories_cfg: dict[str, Any],
    *,
    slot: dict[str, Any] | None = None,
    src_cat: str = "",
) -> list[dict[str, Any]]:
    del slot, src_cat
    return filter_pool_for_red_spirit_targets(pool, tgt_cat, categories_cfg)


def filter_pool_for_physique_compat(
    pool: list[dict[str, Any]],
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """T-086：prep 池不按体态缩水；配对真源=历史状态，防穿模另走 compact/sit。"""
    del slot, categories_cfg, compat_by_tid
    return pool


def filter_prep_donor_indices_for_physique_compat(
    prep: dict[str, Any],
    indices: list[int],
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
) -> list[int]:
    """T-086：同体态排前，其余仍保留（不硬砍）；巡逻人形无同体态时四足提前。
    T-088：脚本飞巡槽（c4200 等）不做体态软排前，只认历史状态。"""
    from donor_msb_compat import _is_script_patrol_flyer_slot

    if _is_script_patrol_flyer_slot(slot, categories_cfg):
        return indices
    from enemy_randomizer_core import (
        donor_physique_bucket,
        slot_physique_bucket,
    )
    if not indices:
        return indices
    slot_b = slot_physique_bucket(slot, categories_cfg)
    donors = prep.get("donors") or []
    if compat_by_tid is None:
        from donor_msb_compat import load_donor_slot_compat

        compat_by_tid = load_donor_slot_compat()
    matched: list[int] = []
    rest: list[int] = []
    for i in indices:
        if i < 0 or i >= len(donors):
            continue
        if donor_physique_bucket(donors[i], categories_cfg, compat_by_tid) == slot_b:
            matched.append(i)
        else:
            rest.append(i)
    if matched:
        return matched + rest
    # T-076：人形巡逻槽无同体态时，四足提前（狼/狗沿路走）
    slot_walk = str(slot.get("walk_route") or "").strip()
    if slot_walk and slot_b == "humanoid" and rest:
        quad: list[int] = []
        other: list[int] = []
        for i in rest:
            if donor_physique_bucket(donors[i], categories_cfg, compat_by_tid) == "quadruped":
                quad.append(i)
            else:
                other.append(i)
        if quad:
            return quad + other
    return rest


def filter_pool_for_trash_targets(
    pool: list[dict[str, Any]],
    tgt_cat: str,
    categories_cfg: dict[str, Any],
    *,
    dlc_trash_enabled: bool = False,
) -> list[dict[str, Any]]:
    """Trash：archetype 表内模型 + 非 Boss 原类；night 等其它类不在此过滤。"""
    from enemy_randomizer_core import (
        BOSS_SOURCE_CATEGORIES,
        is_eligible_trash_donor_model,
        resolve_src_category,
    )
    del dlc_trash_enabled
    if tgt_cat != "trash":
        return pool
    allowlist_on = bool(categories_cfg.get("donor_review_allowlist_enabled", False))
    out: list[dict[str, Any]] = []
    for tpl in pool:
        allowlisted = allowlist_on and is_allowlisted_donor_template(
            tpl, categories_cfg
        )
        model = str(tpl.get("model", ""))
        if not allowlisted and not is_eligible_trash_donor_model(
            model, categories_cfg
        ):
            continue
        # 模板已 enrich 为 trash 时，以模板类为准（避免捐皮类与槽位粗规则不一致）
        tpl_cat = str(tpl.get("category") or "")
        if tpl_cat != "trash":
            cat = resolve_src_category(model, categories_cfg)
            if cat in BOSS_SOURCE_CATEGORIES:
                continue
        out.append(tpl)
    return out


def filter_pool_for_boss_target_donors(
    pool: list[dict[str, Any]],
    tgt_cat: str,
    categories_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """Boss 目标池（2~7）：排除路边小怪皮（如亚人）及脚本不兼容 Boss。"""
    from enemy_randomizer_core import (
        BOSS_SOURCE_CATEGORIES,
        is_boss_pool_excluded_donor,
        is_minor_boss_catalog_donor,
    )
    if tgt_cat not in BOSS_SOURCE_CATEGORIES:
        return pool
    allowlist_on = bool(categories_cfg.get("donor_review_allowlist_enabled", False))
    out: list[dict[str, Any]] = []
    for tpl in pool:
        allowlisted = allowlist_on and is_allowlisted_donor_template(
            tpl, categories_cfg
        )
        if is_boss_pool_excluded_donor(tpl, categories_cfg) and not allowlisted:
            continue
        if should_downgrade_shared_model_to_trash(tpl, categories_cfg) and not allowlisted:
            continue
        if (
            tgt_cat == "minor_boss"
            and not is_minor_boss_catalog_donor(tpl, categories_cfg)
            and not allowlisted
        ):
            continue
        out.append(tpl)
    return out


def filter_pool_for_boss_slot_compat(
    pool: list[dict[str, Any]],
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    tgt_cat: str = "",
    src_cat: str = "",
) -> list[dict[str, Any]]:
    """人形/小型槽：排除巨型捐皮；雾门 _9000 主线 Boss 战点不在此过滤（见 synthetic 雾门池）。"""
    from enemy_randomizer_core import (
        boss_donor_allowed_on_compact_slot,
        is_scripted_dungeon_main_boss_slot,
        resolve_size_tier,
    )
    if is_indoor_dungeon_boss_arena_slot(slot, categories_cfg):
        pool = [
            tpl
            for tpl in pool
            if not is_indoor_dungeon_boss_arena_exclude_donor(
                str(tpl.get("model", "")), categories_cfg
            )
        ]
    if tgt_cat in ("night", "minor_boss", "evergaol"):
        return pool
    if is_scripted_dungeon_main_boss_slot(slot, categories_cfg):
        return pool
    slot_model = str(slot.get("model", ""))
    size_map = categories_cfg.get("size_tier_by_model_prefix", {})
    slot_tier = resolve_size_tier(slot_model, size_map)
    if slot_tier not in ("tiny", "small", "humanoid"):
        return pool
    out: list[dict[str, Any]] = []
    for tpl in pool:
        model = str(tpl.get("model", ""))
        donor_tier = resolve_size_tier(model, size_map)
        if boss_donor_allowed_on_compact_slot(
            model, donor_tier, categories_cfg, slot_tier=slot_tier
        ):
            out.append(tpl)
    return out


def filter_prep_donor_indices_for_slot(
    prep: dict[str, Any],
    indices: list[int],
    slot: dict[str, Any],
    tgt_cat: str,
    categories_cfg: dict[str, Any],
    *,
    src_cat: str = "",
) -> list[int]:
    """生成时重判体型辅助：prep 缓存的 o 池可能早于 categories 变更。"""
    from enemy_randomizer_core import (
        BOSS_TARGET_CATEGORIES,
        boss_donor_allowed_on_compact_slot,
        compact_slot_tiers,
        donor_blocked_for_narrow_placement,
        effective_slot_map_kind,
        is_narrow_environment_boss_slot,
        is_scripted_dungeon_main_boss_slot,
        narrow_map_kinds,
        resolve_size_tier,
        resolve_src_category,
    )
    if not indices:
        return indices
    if is_scripted_dungeon_main_boss_slot(slot, categories_cfg):
        return indices
    indoor_arena = is_indoor_dungeon_boss_arena_slot(slot, categories_cfg)
    narrow_boss = is_narrow_environment_boss_slot(
        slot, categories_cfg, tgt_cat=tgt_cat
    )
    if not src_cat:
        src_cat = str(
            slot.get("src_cat")
            or (slot.get("slot_tags") or {}).get("src_cat")
            or ""
        )
    donors = prep.get("donors") or []
    size_map = categories_cfg.get("size_tier_by_model_prefix", {})
    slot_tier = resolve_size_tier(str(slot.get("model", "")), size_map)
    map_id = str(slot.get("map_id", ""))
    compact = slot_tier in compact_slot_tiers(categories_cfg)
    map_k = effective_slot_map_kind(slot, categories_cfg)
    narrow = map_k in narrow_map_kinds(categories_cfg)
    if not compact and not narrow:
        return indices
    boss_tgt = tgt_cat in BOSS_TARGET_CATEGORIES
    tier_cache: dict[str, str] = {}
    out: list[int] = []
    for i in indices:
        if i < 0 or i >= len(donors):
            continue
        tpl = donors[i]
        model = str(tpl.get("model", ""))
        donor_cat = str(tpl.get("category") or "") or resolve_src_category(
            model, categories_cfg
        )
        donor_tier = tier_cache.get(model)
        if donor_tier is None:
            donor_tier = str(tpl.get("size_tier") or "")
            if not donor_tier:
                donor_tier = resolve_size_tier(model, size_map)
            tier_cache[model] = donor_tier
        if donor_blocked_for_narrow_placement(
            donor_tier,
            slot_tier,
            map_id,
            categories_cfg,
            tgt_cat=tgt_cat,
            entity_name=str(slot.get("name", "")),
            donor_model=model,
            slot=slot,
        ):
            continue
        if (
            compact
            and boss_tgt
            and not narrow_boss
            and not boss_donor_allowed_on_compact_slot(
                model, donor_tier, categories_cfg, slot_tier=slot_tier
            )
        ):
            continue
        if (
            narrow
            and boss_tgt
            and tgt_cat != "night"
            and (
                is_dungeon_incompatible_field_trash_model(model, categories_cfg)
                or is_oversize_boss_model(model)
            )
        ):
            continue
        if indoor_arena and (
            is_indoor_dungeon_boss_arena_exclude_donor(model, categories_cfg)
            or is_oversize_boss_model(model)
            or is_dungeon_incompatible_field_trash_model(model, categories_cfg)
        ):
            continue
        out.append(i)
    return out


def filter_pool_for_safe_donors(
    pool: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """所有目标类别：禁止被动动物与世界实体捐皮。"""
    from enemy_randomizer_core import (
        is_never_donor_hard_block_model,
        is_never_donor_model,
        is_passive_animal_model,
    )
    out: list[dict[str, Any]] = []
    allowlist_on = bool(categories_cfg.get("donor_review_allowlist_enabled", False))
    for tpl in pool:
        model = str(tpl.get("model", ""))
        allowlisted = allowlist_on and is_allowlisted_donor_template(
            tpl, categories_cfg
        )
        if is_never_donor_hard_block_model(model, categories_cfg):
            continue
        if is_never_donor_model(model, categories_cfg) and not allowlisted:
            continue
        if is_passive_animal_model(model, categories_cfg) and not allowlisted:
            continue
        out.append(tpl)
    return out


def filter_pool_for_mount_compat(
    pool: list[dict[str, Any]],
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """马槽不单独随机；配对骑手只走成套池（在 pick 阶段）；其余槽禁止骑马捐皮。"""
    from enemy_randomizer_core import (
        is_horse_mount_model,
        template_is_mount_unit_donor,
    )
    slot_model = str(slot.get("model", ""))
    allowlist_on = bool(categories_cfg.get("donor_review_allowlist_enabled", False))
    if is_horse_mount_model(slot_model, categories_cfg):
        return [
            t
            for t in pool
            if is_horse_mount_model(str(t.get("model", "")), categories_cfg)
        ]

    def _ok(t: dict[str, Any]) -> bool:
        if not template_is_mount_unit_donor(t, categories_cfg):
            return True
        return allowlist_on and is_allowlisted_donor_template(t, categories_cfg)

    return [t for t in pool if _ok(t)]


def _compat_pool_for_slot_tier(
    compat_pools: dict[tuple[str, str, str], list[dict[str, Any]]],
    tgt_cat: str,
    slot_tier: str,
    map_k: str,
    src_cat: str,
) -> list[dict[str, Any]]:
    """compat 预池按槽体型索引；Boss 源槽体型偏小且同类互抽时回退 boss 档预池。"""
    from enemy_randomizer_core import BOSS_SOURCE_CATEGORIES
    pool = list(compat_pools.get((tgt_cat, slot_tier, map_k), []))
    if pool or src_cat != tgt_cat or tgt_cat not in BOSS_SOURCE_CATEGORIES:
        return pool
    for tier in ("large", "medium", "humanoid", "tiny"):
        if tier == slot_tier:
            continue
        alt = compat_pools.get((tgt_cat, tier, map_k), [])
        if alt:
            return list(alt)
    return []


def filter_slot_donor_pool(
    compat_pools: dict[tuple[str, str, str], list[dict[str, Any]]],
    slot: dict[str, Any],
    tgt_cat: str,
    src_cat: str,
    *,
    categories_cfg: dict[str, Any],
    dlc_pool_mode: str,
    size_map: dict[str, str] | None = None,
    donor_msb_compat: dict[str, dict[str, Any]] | None = None,
    whitelist_receptor_index: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Per-slot filtered donor pool for a target category (seed-independent)."""
    from enemy_randomizer_core import (
        dlc_trash_enabled_for_slot,
        effective_slot_map_kind,
        filter_pool_by_dlc_mode,
        is_dlc_enemy_map,
        is_scripted_dungeon_main_boss_slot,
        resolve_size_tier,
    )
    slot_tags = slot.get("slot_tags") or {}
    map_id = str(slot.get("map_id", ""))
    map_k = effective_slot_map_kind(slot, categories_cfg)
    tier_map = size_map or categories_cfg.get("size_tier_by_model_prefix", {})
    slot_tier = resolve_size_tier(str(slot.get("model", "")), tier_map)
    pool = _compat_pool_for_slot_tier(
        compat_pools, tgt_cat, slot_tier, map_k, src_cat
    )
    pool = filter_pool_by_dlc_mode(
        pool,
        slot_is_dlc=is_dlc_enemy_map(map_id, categories_cfg),
        dlc_pool_mode=dlc_pool_mode,
        categories_cfg=categories_cfg,
    )
    if tgt_cat != "night":
        pool = filter_pool_for_mount_compat(pool, slot, categories_cfg)
    dlc_trash_ok = dlc_trash_enabled_for_slot(dlc_pool_mode, map_id, categories_cfg)
    pool = filter_pool_for_trash_targets(
        pool,
        tgt_cat,
        categories_cfg,
        dlc_trash_enabled=dlc_trash_ok,
    )
    pool = filter_pool_for_red_spirit_targets(pool, tgt_cat, categories_cfg)
    pool = filter_pool_for_field_boss_targets(
        pool, tgt_cat, categories_cfg, slot=slot, src_cat=src_cat
    )
    pool = filter_pool_for_boss_target_donors(pool, tgt_cat, categories_cfg)
    pool = filter_pool_for_scripted_fog_boss_donors(
        pool, slot, tgt_cat, categories_cfg
    )
    pool = filter_pool_for_boss_slot_compat(
        pool, slot, categories_cfg, tgt_cat=tgt_cat, src_cat=src_cat
    )
    pool = filter_pool_for_narrow_placement(
        pool, slot, categories_cfg, size_map=tier_map, tgt_cat=tgt_cat
    )
    pool = filter_pool_for_anchor_plant_slot(pool, slot, categories_cfg)
    pool = filter_pool_for_safe_donors(pool, categories_cfg)
    skip_hist = tgt_cat == "major_boss" and is_scripted_dungeon_main_boss_slot(
        slot, categories_cfg
    )
    if donor_msb_compat is not None and not skip_hist:
        from donor_msb_compat import filter_pool_for_donor_msb_compat

        pool = filter_pool_for_donor_msb_compat(
            pool,
            slot,
            donor_msb_compat,
            whitelist_receptor_index,
            categories_cfg=categories_cfg,
        )
    pool = filter_pool_for_physique_compat(pool, slot, categories_cfg, donor_msb_compat)
    return pool

