"""T-036 / T-037 — enemy index scan + spawn map generation."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Any

from boss_npc_detect import (
    is_dungeon_incompatible_field_trash_model,
    is_dungeon_map_id,
    is_force_trash_model,
    is_indoor_dungeon_boss_arena_slot,
    is_indoor_dungeon_boss_arena_exclude_donor,
    is_oversize_boss_model,
    is_red_spirit_combat_slot,
    is_red_spirit_model,
    is_script_event_npc_slot,
    is_summon_clone_donor_template,
    is_talk_npc_id,
    should_downgrade_shared_model_to_trash,
    resolve_entity_category,
    resolve_template_category_with_boss_detect,
    slot_entity_token,
    template_is_cnv_boss_tag_npc,
    template_is_cnv_new_npc_red_spirit,
    template_is_cnv_pool7_marked_npc,
)
from donor_pool_review_allowlist import (
    apply_review_allowlist_category,
    is_allowlisted_donor_template,
    normalize_category_id,
)

from paths import (
    CACHE_DIR,
    GAME_DIR,
    OUTPUT_DIR,
    OUTPUT_RUNTIME,
    DEFAULT_ENEMY_SPAWN_MAP,
    SCRIPT_DIR,
    ensure_output_dirs,
)
from enemy_spawn_bundle import (
    SpawnBundleError,
    parse_spawn_map_header,
    resolve_spawn_map_sidecar_paths,
    spawn_map_seed_from_path,
    spawn_map_sidecar_paths,
    validate_spawn_bundle,
)
from enemy_apply_runner import EnemyApplyResult, prune_stale_overlay_msbs, run_enemy_apply

DEFAULT_INDEX_PATH = CACHE_DIR / "enemy_index.json"
DEFAULT_CATEGORIES_PATH = SCRIPT_DIR / "enemy_categories.json"
DEFAULT_SIZE_TIERS_PATH = SCRIPT_DIR / "enemy_size_tiers.json"
DEFAULT_ARCHETYPES_PATH = SCRIPT_DIR / "enemy_archetypes.json"
DEFAULT_RUNE_TIERS_PATH = SCRIPT_DIR / "enemy_rune_tiers.json"
DEFAULT_GAMEAREA_SOULS_PATH = SCRIPT_DIR / "enemy_gamearea_souls.json"
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "config.json"
MSB_POC_PROJECT = SCRIPT_DIR.parent / "cnv_enemy_poc" / "MsbEnemyPoc" / "MsbEnemyPoc.csproj"
MSB_POC_EXE = (
    SCRIPT_DIR.parent / "cnv_enemy_poc" / "MsbEnemyPoc" / "bin" / "Release" / "net8.0" / "MsbEnemyPoc.exe"
)

CATEGORY_ORDER = (
    "trash",
    "elite",
    "minor_boss",
    "evergaol",
    "night",
    "major_boss",
)

BOSS_SOURCE_CATEGORIES = frozenset({"minor_boss", "major_boss", "evergaol"})
BOSS_TARGET_CATEGORIES = frozenset({"minor_boss", "major_boss", "evergaol"})
TRASH_LIKE_TARGET_CATEGORIES = frozenset({"trash", "elite"})
RUNE_TIER_CAP_RED_SPIRIT_TGT = frozenset({"minor_boss", "evergaol", "cnv_special"})


# night（红灵）：按捐皮原版 getSoul/GameArea，不做 trash 式阶梯封顶（2026-08-04）

# 击杀卢恩数额：仅按 by_category 阶梯 + 地图 tier 缩放（2026-07-31 废止 Boss ÷10）


def resolve_enemy_worker_count(config_value: int | None = None) -> int:
    """0 / None = all logical CPUs (gaming PC default)."""
    cpus = os.cpu_count() or 4
    if config_value is not None and int(config_value) > 0:
        return max(1, int(config_value))
    return cpus


def resolve_prep_worker_count(config_value: int | None = None) -> int:
    """Slot prep 多进程：默认=全部逻辑核（与 resolve_enemy_worker_count 一致）。"""
    return resolve_enemy_worker_count(config_value)


def resolve_enemy_apply_parallel(
    parallel_cfg: int | None = None,
    io_multiplier: float | None = None,
) -> int:
    """Apply-map is I/O + compression heavy — oversubscribe threads by default."""
    base = resolve_enemy_worker_count(parallel_cfg)
    mult = 3.0 if io_multiplier is None else float(io_multiplier)
    if mult <= 1.0:
        return base
    return min(96, max(base, int(base * mult)))


def resolve_enemy_apply_max_parallel(max_cfg: int | None = None) -> int:
    """Upper cap for parallel / dynamic workers (512 caused RAM+disk stall)."""
    cpus = os.cpu_count() or 4
    if max_cfg is not None and int(max_cfg) > 0:
        return max(1, int(max_cfg))
    return min(96, max(cpus * 2, 32))


def resolve_enemy_apply_map_inflight(inflight_cfg: int | None = None) -> int:
    """Max maps being read+patched+written at once (RAM + SSD)."""
    if inflight_cfg is not None and int(inflight_cfg) > 0:
        return max(1, int(inflight_cfg))
    return 48


def _enemy_gui_perf(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    if cfg is None:
        try:
            cfg = _load_json(DEFAULT_CONFIG_PATH) if DEFAULT_CONFIG_PATH.is_file() else {}
        except Exception:
            cfg = {}
    return cfg.get("enemy_gui") or {}


CATEGORY_DISPLAY_ZH: dict[str, str] = {
    "trash": "路边小怪",
    "elite": "精英",
    "minor_boss": "洞穴/副本Boss",
    "evergaol": "场地Boss",
    "night": "红灵",
    "major_boss": "主线大Boss",
}

CATEGORY_NUM: dict[str, int] = {
    cat_id: idx + 1 for idx, cat_id in enumerate(CATEGORY_ORDER)
}


@dataclass
class EnemyGenerateResult:
    seed: int
    spawn_map_path: Path
    spoiler_path: Path
    slots_total: int
    slots_replaced: int
    slots_skipped: int
    apply_spawn_path: Path | None = None
    slots_skipped_large: int = 0
    slots_skipped_passive_animal: int = 0
    slots_skipped_npc_slot: int = 0
    slots_skipped_scarab: int = 0
    slots_skipped_dense_keep: int = 0
    dlc_donor_hits: int = 0
    risk_report_path: Path | None = None
    spoiler_zh_path: Path | None = None
    archetypes_hit: int = 0
    models_hit: int = 0
    spawn_model_names: list[str] = field(default_factory=list)
    gatefront_dlc_models: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


# 监牢源槽（3 池）允许的目标：3~7 池；禁止 1 池 trash、2 池洞穴小 Boss
# 洞穴/墓地 Boss 源槽（2 池）：只抽 2~7 池；禁止 1 池 trash（防 Boss 房刷肉泥/亚人）


# 兼容旧名 — 见文末 B2 facade re-export

_ENEMY_CALC_PHASE_SPAN: dict[str, tuple[float, float]] = {
    "prep_cache": (0.0, 0.08),
    "prep": (0.08, 0.04),
    "scan": (0.12, 0.50),
    "pick": (0.62, 0.36),
    "write": (0.98, 0.02),
}


def _enemy_calc_progress(
    on_progress: Any | None,
    phase: str,
    done: int,
    total: int,
    msg: str,
    *,
    every: int = 200,
) -> None:
    if not on_progress:
        return
    if total > 0 and done not in (0, total) and done % every != 0:
        return
    on_progress(phase, done, total, msg)


def run_enemy_randomize(
    cfg: dict,
    *,
    seed: int | None = None,
    index_path: Path | None = None,
    out_dir: Path | None = None,
    map_filter: str | None = None,
    on_progress: Any | None = None,
) -> EnemyGenerateResult:
    _t_run = time.perf_counter()
    _phase_mark: dict[str, float] = {}

    enemy_gui = cfg.get("enemy_gui", {})
    weights = enemy_gui.get("category_weights") or {}
    mob_drop_mode = normalize_mob_drop_mode(
        enemy_gui.get("mob_drop_mode"),
        keep_original_drops=enemy_gui.get("keep_original_drops"),
    )
    dlc_pool_mode = str(enemy_gui.get("dlc_pool_mode", "mixed"))
    if dlc_pool_mode not in ("mixed", "separate"):
        dlc_pool_mode = "mixed"

    seed = int(seed if seed is not None else cfg.get("seed", 1))
    out_dir = Path(out_dir or cfg.get("output_dir", OUTPUT_RUNTIME))
    if not out_dir.is_absolute():
        out_dir = SCRIPT_DIR / out_dir
    ensure_output_dirs()
    out_dir.mkdir(parents=True, exist_ok=True)

    index = load_enemy_index(index_path)
    _enemy_calc_progress(on_progress, "prep", 0, 1, "敌人：加载索引…")
    categories_cfg = _load_json(DEFAULT_CATEGORIES_PATH)
    rune_cfg = _load_json(DEFAULT_RUNE_TIERS_PATH)
    rune_by_cat = {k: int(v) for k, v in rune_cfg.get("by_category", {}).items()}
    keep_original_mult = int(rune_cfg.get("keep_original_multiplier", 1) or 1)
    soul_map = load_npc_soul_map(Path(cfg.get("csv_dir")) if cfg.get("csv_dir") else None)
    gamearea_by_npc, gamearea_by_model = load_gamearea_soul_maps()

    global ARCHETYPE_INDEX_CACHE
    ARCHETYPE_INDEX_CACHE = None
    archetype_index = load_archetype_index(categories_cfg)
    npc_csv_dir = Path(cfg.get("csv_dir")) if cfg.get("csv_dir") else GAME_DIR / "csv"
    if hasattr(npc_csv_dir, "_resolved"):
        try:
            npc_csv_dir = npc_csv_dir._resolved()
        except FileNotFoundError:
            pass

    from boss_npc_detect import load_npc_rows
    from dlc_donor_pool import (
        build_vanilla_donor_npc_by_model,
        resolve_synthetic_template_donor_npc,
    )

    npc_by_id_for_hp = load_npc_rows(npc_csv_dir)
    vanilla_npc_by_model = build_vanilla_donor_npc_by_model(
        index.get("templates") or [],
        npc_by_id=npc_by_id_for_hp,
    )

    from enemy_slot_prep import (
        build_slot_prep,
        explain_prep_cache_miss,
        load_slot_prep,
        load_slot_prep_if_valid,
        prep_meta,
        warn_stale_prep_version,
    )

    warn_stale_prep_version()

    prep_meta_current = prep_meta(dlc_pool_mode=dlc_pool_mode)

    def _prep_cache_progress(phase: str, done: int, total: int, msg: str) -> None:
        if on_progress:
            on_progress("prep_cache", done, max(total, 1), msg)

    prep_path = load_slot_prep_if_valid(
        meta=prep_meta_current,
        on_progress=_prep_cache_progress,
    )
    prep_rebuild_reason = ""
    if prep_path is None:
        prep_rebuild_reason = explain_prep_cache_miss(meta=prep_meta_current)
        _enemy_calc_progress(
            on_progress,
            "prep_cache",
            0,
            1,
            f"敌人：槽位缓存失效 — {prep_rebuild_reason}",
            every=1,
        )
        prep_path = build_slot_prep(
            index,
            categories_cfg,
            dlc_pool_mode=dlc_pool_mode,
            npc_csv_dir=npc_csv_dir,
            workers=resolve_prep_worker_count(_enemy_gui_perf(cfg).get("prep_workers")),
            on_progress=_prep_cache_progress,
        )
        prep_cache_note = (
            "slot_prep_cache=built（本地自动构建；维护者可 prep 后提交 .gz+.meta.json）"
        )
    else:
        prep_cache_note = "slot_prep_cache=on"

    mount_pair_donors_by_kind = build_mount_pair_donors(
        index.get("templates", []), categories_cfg
    )
    mount_pair_total = sum(len(v) for v in mount_pair_donors_by_kind.values())

    assignments: list[dict[str, Any]] = []
    warnings: list[str] = [prep_cache_note]
    if prep_rebuild_reason:
        warnings.append(f"slot_prep_cache=rebuild reason={prep_rebuild_reason}")
    if not mount_pair_randomize_enabled(categories_cfg):
        warnings.append(
            "mount_pair_randomize=off（黑夜骑兵/树守卫等成套骑马槽保持原版；见 T-056）"
        )
    skipped = 0
    skipped_large = 0
    skipped_passive_animal = 0
    skipped_npc_slot = 0
    skipped_scarab = 0
    dlc_donor_hits = 0
    pick_plans: list[_SlotPickPlan] = []

    prep = load_slot_prep(prep_path, on_progress=_prep_cache_progress)
    _phase_mark["prep"] = time.perf_counter()
    _enemy_calc_progress(
        on_progress,
        "scan",
        0,
        1,
        "敌人：规划替换槽位…",
    )
    pick_plans, skip_counts, prep_warnings = _pick_plans_from_prep(
        prep,
        index,
        weights,
        seed,
        categories_cfg=categories_cfg,
        map_filter=map_filter,
        mount_pair_donors_by_kind=mount_pair_donors_by_kind,
        npc_csv_dir=npc_csv_dir,
        dlc_pool_mode=dlc_pool_mode,
        on_progress=on_progress,
        prep_trusted=not bool(prep_rebuild_reason),
    )
    warnings.extend(prep_warnings)
    _phase_mark["scan"] = time.perf_counter()
    skipped = skip_counts["skipped"]
    skipped_large = skip_counts["skipped_large"]
    skipped_passive_animal = skip_counts["skipped_passive_animal"]
    skipped_npc_slot = skip_counts["skipped_npc_slot"]
    skipped_scarab = skip_counts["skipped_scarab"]
    skipped_dense_keep = int(skip_counts.get("skipped_dense_keep") or 0)
    skipped += skipped_dense_keep
    trash_arch_in_pool = len(archetype_index.trash_archetype_ids)
    warnings.append(
        f"donor_pool trash archetypes(cache)={trash_arch_in_pool} "
        f"pick_plans={len(pick_plans)}"
    )
    warnings.append(f"donor_pool mount_pairs={mount_pair_total}")

    slots_total = len(index.get("slots", []))
    if map_filter:
        slots_total = sum(
            1 for s in index.get("slots", []) if str(s.get("map_id")) == map_filter
        )

    plan_total = len(pick_plans)
    balanced_donor_map = build_balanced_pool_donor_assignments(
        pick_plans,
        prep,
        seed,
        categories_cfg,
    )
    from donor_vanilla_states import (
        build_model_vanilla_state_index,
        vanilla_state_index_cache_key,
    )

    index_slots = index.get("slots", [])
    vanilla_key = vanilla_state_index_cache_key(index_slots)
    model_vanilla_index = build_model_vanilla_state_index(
        index_slots, cache_key=vanilla_key
    )
    from donor_msb_compat import load_donor_slot_compat

    spawn_compat_by_tid = load_donor_slot_compat()
    from donor_msb_compat import donor_slot_compat_reject_reason

    _enemy_calc_progress(
        on_progress,
        "pick",
        0,
        max(plan_total, 1),
        f"敌人：抽签捐皮 0/{plan_total}…",
    )

    def append_assignment(
        *,
        slot: dict[str, Any],
        map_id: str,
        entity_name: str,
        src_cat: str,
        tgt_cat: str,
        template: dict[str, Any],
        arch_id: str,
        arch_label: str,
        pair_id: str = "",
        demount: bool = False,
        suppress_mount: bool = False,
    ) -> None:
        if suppress_mount:
            slot_model = str(slot.get("model", "") or "mount")
            row = {
                "map_id": map_id,
                "entity_name": entity_name,
                "src_cat": src_cat,
                "tgt_cat": tgt_cat,
                "template_id": CNV_SUPPRESS_MOUNT_TEMPLATE,
                "donor_map": "",
                "donor_entity": "",
                "model": slot_model,
                "npc": 0,
                "think": 0,
                "chara": -1,
                "rune_amount": 0,
                "archetype_id": "mount_bind",
                "archetype_zh": "马槽沉底",
                "suppress_mount": True,
            }
            if pair_id:
                row["mount_pair_id"] = pair_id
            assignments.append(row)
            return

        rune_amount = lookup_rune_amount(
            mob_drop_mode=mob_drop_mode,
            slot=slot,
            template=template,
            src_cat=src_cat,
            tgt_cat=tgt_cat,
            rune_tiers=rune_by_cat,
            soul_map=soul_map,
            gamearea_by_npc=gamearea_by_npc,
            gamearea_by_model=gamearea_by_model,
            keep_original_multiplier=keep_original_mult,
            categories_cfg=categories_cfg,
            map_id=map_id,
        )
        template_id = str(template.get("template_id") or "")
        if demount and template_id:
            template_id = f"{template_id}{CNV_DEMOUNT_TEMPLATE_SUFFIX}"
        from dlc_donor_pool import resolve_valid_donor_npc

        donor_npc = resolve_donor_npc_id(
            resolve_synthetic_template_donor_npc(
                template,
                vanilla_npc_by_model,
                npc_by_id=npc_by_id_for_hp,
            ),
            categories_cfg,
        )
        donor_npc = resolve_valid_donor_npc(
            donor_npc,
            str(template.get("model") or ""),
            npc_by_id_for_hp,
        )
        from donor_vanilla_states import resolve_slot_runtime_npc_and_think

        donor_npc, think = resolve_slot_runtime_npc_and_think(
            slot,
            template,
            donor_npc,
            categories_cfg,
            model_vanilla_index,
        )
        from npc_think_sanitize import think_matches_model_family, think_param_has_id

        model_l = str(template.get("model") or "")
        if think > 0 and not think_matches_model_family(model_l, think):
            warnings.append(
                f"think_family_blocked {map_id}:{entity_name} "
                f"model={model_l} think={think} tpl={template_id}"
            )
            return
        if think > 0 and not think_param_has_id(think):
            warnings.append(
                f"think_param_missing {map_id}:{entity_name} "
                f"model={model_l} think={think} tpl={template_id}"
            )
            return
        check_tid = str(template.get("template_id") or template_id).split("|", 1)[0]
        if demount and check_tid.endswith(CNV_DEMOUNT_TEMPLATE_SUFFIX):
            check_tid = check_tid[: -len(CNV_DEMOUNT_TEMPLATE_SUFFIX)]
        compat_reject = donor_slot_compat_reject_reason(
            slot,
            check_tid,
            spawn_compat_by_tid,
            categories_cfg=categories_cfg,
        )
        if compat_reject:
            warnings.append(
                f"spawn_compat_blocked {map_id}:{entity_name} "
                f"{compat_reject} tpl={check_tid}"
            )
            return
        try:
            src_npc = int(slot.get("npc") or 0)
        except (TypeError, ValueError):
            src_npc = 0
        row: dict[str, Any] = {
            "map_id": map_id,
            "entity_name": entity_name,
            "src_cat": src_cat,
            "tgt_cat": tgt_cat,
            "template_id": template_id,
            "donor_map": template.get("donor_map"),
            "donor_entity": template.get("donor_entity"),
            "model": template.get("model"),
            "npc": donor_npc,
            "think": think,
            "chara": template.get("chara", -1),
            "rune_amount": rune_amount,
            "archetype_id": arch_id,
            "archetype_zh": arch_label,
            "placement_kind": _slot_placement_kind(slot),
            "walk_route": str(slot.get("walk_route") or ""),
            "backup_anim": int(slot.get("backup_anim", -1) or -1),
        }
        if src_cat in BOSS_SOURCE_CATEGORIES and src_npc > 0:
            row["src_npc"] = src_npc
        apply_radahn_phase1_think(row, slot, categories_cfg)
        if demount:
            row["demount"] = True
        if pair_id:
            row["mount_pair_id"] = pair_id
        assignments.append(row)

    for plan_i, plan in enumerate(pick_plans, start=1):
        if plan.mount_pair_pool and plan.partner_mount_slot:
            partner = plan.partner_mount_slot
            rng2 = slot_rng(seed, plan.map_id, plan.entity_name, 2)
            pair = pick_mount_pair_donor(plan.mount_pair_pool, rng2)
            arch_label = plan.mount_pair_label_zh or mount_pair_kind_label(
                pair, categories_cfg
            )
            append_assignment(
                slot=plan.slot,
                map_id=plan.map_id,
                entity_name=plan.entity_name,
                src_cat=plan.src_cat,
                tgt_cat=plan.tgt_cat,
                template=pair.rider_tpl,
                arch_id=pair.kind_id,
                arch_label=arch_label,
                pair_id=pair.pair_id,
            )
            append_assignment(
                slot=partner,
                map_id=str(partner["map_id"]),
                entity_name=str(partner["name"]),
                src_cat=plan.src_cat,
                tgt_cat=plan.tgt_cat,
                template=pair.mount_tpl,
                arch_id=pair.kind_id,
                arch_label=arch_label,
                pair_id=pair.pair_id,
            )
            _enemy_calc_progress(
                on_progress,
                "pick",
                plan_i,
                plan_total,
                f"敌人：抽签捐皮 {plan_i}/{plan_total}…",
                every=100,
            )
            continue

        rng2 = slot_rng(seed, plan.map_id, plan.entity_name, 2)
        slot_model = str(plan.slot.get("model") or "")
        if not slot_model:
            em = re.match(r"(c\d{4})", plan.entity_name, re.I)
            slot_model = em.group(1) if em else ""
        slot_model_l = _norm_model_key(slot_model)
        balanced_key = (plan.map_id, plan.entity_name)
        if balanced_key in balanced_donor_map:
            template, arch_id, arch_label = donor_pick_from_prep_index(
                prep,
                balanced_donor_map[balanced_key],
                tgt_cat=plan.tgt_cat,
                archetype_index=archetype_index,
                categories_cfg=categories_cfg,
            )
            if _norm_model_key(str(template.get("model", ""))) == slot_model_l and slot_model_l:
                template = None
        else:
            template = None
        if template is None:
            try:
                template, arch_id, arch_label = pick_donor_by_archetype_indices(
                    prep,
                    plan.donor_indices,
                    rng2,
                    tgt_cat=plan.tgt_cat,
                    archetype_index=archetype_index,
                    categories_cfg=categories_cfg,
                    slot_model=slot_model,
                )
            except SameModelExhausted:
                warnings.append(
                    f"same_model_exhausted {plan.map_id}:{plan.entity_name} "
                    f"model={slot_model}"
                )
                _enemy_calc_progress(
                    on_progress,
                    "pick",
                    plan_i,
                    plan_total,
                    f"敌人：抽签捐皮 {plan_i}/{plan_total}…",
                    every=100,
                )
                continue
        if slot_model_l and _norm_model_key(str(template.get("model", ""))) == slot_model_l:
            warnings.append(
                f"same_model_exhausted {plan.map_id}:{plan.entity_name} model={slot_model}"
            )
            continue
        if plan.tgt_cat == "night":
            arch_label = night_model_label(str(template.get("model", "")), categories_cfg)
        if template_is_dlc_boss_donor(template, categories_cfg):
            dlc_donor_hits += 1

        if template_is_mount_unit_donor(template, categories_cfg):
            warnings.append(
                f"blocked_mount_donor {plan.map_id}:{plan.entity_name} "
                f"model={template.get('model')}"
            )
            _enemy_calc_progress(
                on_progress,
                "pick",
                plan_i,
                plan_total,
                f"敌人：抽签捐皮 {plan_i}/{plan_total}…",
                every=100,
            )
            continue

        demount = bool(
            slot_is_mounted_rider(plan.slot, categories_cfg)
            and not slot_is_mount_rider_slot(plan.slot, categories_cfg)
        )
        append_assignment(
            slot=plan.slot,
            map_id=plan.map_id,
            entity_name=plan.entity_name,
            src_cat=plan.src_cat,
            tgt_cat=plan.tgt_cat,
            template=template,
            arch_id=arch_id,
            arch_label=arch_label,
            demount=demount,
        )

        _enemy_calc_progress(
            on_progress,
            "pick",
            plan_i,
            plan_total,
            f"敌人：抽签捐皮 {plan_i}/{plan_total}…",
            every=100,
        )

    gap_count = _audit_spawn_plan_gaps(pick_plans, assignments, warnings)
    if gap_count:
        warnings.append(f"spawn_plan_gap_total={gap_count}")

    warnings.append(
        "enemy_archetype_lottery=on (原型均匀→皮均匀；步兵禁骑马；配对骑手=全局成套骑马池)"
    )
    _phase_mark["pick"] = time.perf_counter()

    occupied_keys = {(str(a["map_id"]), str(a["entity_name"])) for a in assignments}
    decorative_suppress = build_decorative_suppress_assignments(
        index,
        categories_cfg,
        map_filter=map_filter,
        occupied_keys=occupied_keys,
        npc_csv_dir=npc_csv_dir,
    )
    if decorative_suppress:
        assignments.extend(decorative_suppress)
        warnings.append(f"decorative_suppress={len(decorative_suppress)}")

    spawn_path = out_dir / "cnv_enemy_spawn_map.txt"
    staging_dir = out_dir / ".apply_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    apply_spawn_path = staging_dir / f"cnv_enemy_spawn_map_{seed}.txt"
    spoiler_path = out_dir / "spoiler_enemies.txt"
    spoiler_zh_path = out_dir / "spoiler_enemies_zh.txt"
    risk_path = out_dir / "cnv_enemy_spawn_map_risk.txt"
    _enemy_calc_progress(on_progress, "write", 0, 1, "敌人：写入对照表…")
    try:
        from npc_soul_copies import ensure_radahn_phase1_assets

        ensure_radahn_phase1_assets()
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"radahn_phase1_pre_write_FAILED: {exc}")
    copies = write_spawn_map(
        apply_spawn_path,
        seed,
        assignments,
        mob_drop_mode,
        difficulty=enemy_gui.get("difficulty"),
    )
    prune_stale_flat_sidecars(staging_dir, seed)
    warnings.append(
        f"spawn_written slots={len(assignments)} path={apply_spawn_path.name}"
    )
    if map_filter:
        audit_path = write_map_spawn_audit(
            map_id=map_filter,
            seed=seed,
            index=index,
            categories_cfg=categories_cfg,
            pick_plans=pick_plans,
            assignments=assignments,
            warnings=warnings,
            out_path=out_dir / f"map_spawn_audit_{map_filter}.txt",
            npc_csv_dir=npc_csv_dir,
            prep=prep,
        )
        warnings.append(f"spawn_audit={audit_path.name}")
    try:
        shutil.copy2(apply_spawn_path, spawn_path)
        apply_sidecars = spawn_map_sidecar_paths(apply_spawn_path, seed)
        flat_sidecars = {
            "copies": "cnv_npc_soul_copies.json",
            "npc_csv": "NpcParam.csv",
            "skipped": "cnv_npc_soul_copies_skipped.txt",
        }
        for key, flat_name in flat_sidecars.items():
            side = apply_sidecars[key]
            if side.is_file():
                shutil.copy2(side, spawn_path.with_name(flat_name))
    except OSError as exc:
        warnings.append(f"spawn_mirror_failed: {exc}")
    skipped_path = spawn_map_sidecar_paths(apply_spawn_path, seed)["skipped"]
    if skipped_path.is_file():
        skipped_ids = [
            ln.strip()
            for ln in skipped_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        if skipped_ids:
            warnings.append(
                f"t052_npc_copy_skipped_missing={len(skipped_ids)} "
                f"sample={','.join(skipped_ids[:6])}"
            )
    try:
        from npc_soul_copies import ensure_radahn_phase1_assets, patch_regulation_npc_copies

        copies_json = spawn_map_sidecar_paths(apply_spawn_path, seed)["copies"]
        status = patch_regulation_npc_copies(
            copies_json if copies_json.is_file() else None,
            clear_only=not bool(copies),
        )
        warnings.append(f"t052_{status}")
        warnings.append(f"radahn_phase1_{ensure_radahn_phase1_assets()}")
    except Exception as exc:  # noqa: BLE001 — surface to GUI/spoiler
        warnings.append(f"t052_npc_copy_patch_FAILED: {exc}")
    write_spoiler(spoiler_path, seed, assignments, warnings)
    write_spoiler_zh(
        spoiler_zh_path,
        seed,
        assignments,
        categories_cfg,
        mob_drop_mode=mob_drop_mode,
        category_weights=weights,
    )
    write_risk_report(risk_path, seed, assignments, categories_cfg)
    for legacy_name in ("spoiler_enemies.txt", "spoiler_enemies_zh.txt"):
        legacy = OUTPUT_DIR / legacy_name
        src = out_dir / legacy_name
        if src.is_file() and src.resolve() != legacy.resolve():
            legacy.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    _enemy_calc_progress(
        on_progress,
        "write",
        1,
        1,
        f"敌人：表完成（{len(assignments)} 槽）",
    )
    _phase_mark["write"] = time.perf_counter()
    t_prep = _phase_mark.get("prep", _t_run) - _t_run
    t_scan = _phase_mark.get("scan", _phase_mark.get("prep", _t_run)) - _phase_mark.get(
        "prep", _t_run
    )
    t_pick = _phase_mark.get("pick", _phase_mark.get("scan", _t_run)) - _phase_mark.get(
        "scan", _phase_mark.get("prep", _t_run)
    )
    t_write = _phase_mark["write"] - _phase_mark.get("pick", _phase_mark.get("scan", _t_run))
    t_total = _phase_mark["write"] - _t_run
    warnings.append(
        f"phase_timing prep={t_prep:.1f}s scan={t_scan:.1f}s pick={t_pick:.1f}s "
        f"write={t_write:.1f}s total={t_total:.1f}s"
    )
    warnings.append(f"用时={t_total:.1f}s")
    _enemy_calc_progress(
        on_progress,
        "write",
        1,
        1,
        f"敌人：生成完成（{len(assignments)} 槽，用时 {t_total:.1f} 秒）",
    )

    from enemy_category_rules import is_dlc_trash_donor_model

    return EnemyGenerateResult(
        seed=seed,
        spawn_map_path=spawn_path,
        apply_spawn_path=apply_spawn_path,
        spoiler_path=spoiler_path,
        spoiler_zh_path=spoiler_zh_path,
        slots_total=slots_total,
        slots_replaced=len(assignments),
        slots_skipped=skipped,
        slots_skipped_large=skipped_large,
        slots_skipped_passive_animal=skipped_passive_animal,
        slots_skipped_npc_slot=skipped_npc_slot,
        slots_skipped_scarab=skipped_scarab,
        slots_skipped_dense_keep=skipped_dense_keep,
        dlc_donor_hits=dlc_donor_hits,
        archetypes_hit=len(
            {str(a.get("archetype_id", "")) for a in assignments if a.get("archetype_id")}
        ),
        models_hit=len({str(a.get("model", "")) for a in assignments}),
        spawn_model_names=sorted(
            {str(a.get("model", "")) for a in assignments if a.get("model")}
        ),
        gatefront_dlc_models=sorted(
            {
                str(a.get("model", ""))
                for a in assignments
                if str(a.get("map_id", "")).startswith("m60")
                and a.get("model")
                and is_dlc_trash_donor_model(str(a.get("model", "")), categories_cfg)
            }
        ),
        risk_report_path=risk_path,
        warnings=warnings,
    )


def run_enemy_smoke(
    cfg: dict,
    *,
    seed: int | None = None,
    map_filter: str | None = None,
) -> dict[str, Any]:
    """仅跑槽位扫描+捐皮池校验（不写 spawn 表）；单图通常数秒、全图约 1～2 分钟。"""
    import time

    from enemy_slot_prep import load_slot_prep, load_slot_prep_if_valid, prep_meta, warn_stale_prep_version

    warn_stale_prep_version()

    t0 = time.perf_counter()
    enemy_gui = cfg.get("enemy_gui", {})
    weights = enemy_gui.get("category_weights") or {}
    dlc_pool_mode = str(enemy_gui.get("dlc_pool_mode", "mixed"))
    seed = int(seed if seed is not None else cfg.get("seed", 1))
    index = load_enemy_index()
    categories_cfg = _load_json(DEFAULT_CATEGORIES_PATH)
    npc_csv_dir = Path(cfg.get("csv_dir")) if cfg.get("csv_dir") else GAME_DIR / "csv"
    prep = load_slot_prep(load_slot_prep_if_valid(meta=prep_meta(dlc_pool_mode=dlc_pool_mode)))
    mount_pair_donors_by_kind = build_mount_pair_donors(
        index.get("templates", []), categories_cfg
    )
    pick_plans, skip_counts, warnings = _pick_plans_from_prep(
        prep,
        index,
        weights,
        seed,
        categories_cfg=categories_cfg,
        map_filter=map_filter,
        mount_pair_donors_by_kind=mount_pair_donors_by_kind,
        npc_csv_dir=npc_csv_dir,
        dlc_pool_mode=dlc_pool_mode,
    )
    participate = 0
    for slot in index.get("slots", []):
        if map_filter and str(slot.get("map_id", "")) != map_filter:
            continue
        if describe_slot_policy(slot, categories_cfg).get("policy") == "participate":
            participate += 1
    plan_keys = {(p.map_id, p.entity_name) for p in pick_plans}
    missing: list[tuple[str, str, str]] = []
    for slot in index.get("slots", []):
        if map_filter and str(slot.get("map_id", "")) != map_filter:
            continue
        if describe_slot_policy(slot, categories_cfg).get("policy") != "participate":
            continue
        key = (str(slot.get("map_id", "")), str(slot.get("name", "")))
        if key not in plan_keys:
            missing.append((key[0], key[1], str(slot.get("model", ""))))
    empty_pool = [w for w in warnings if w.startswith("empty pool")]
    elapsed = time.perf_counter() - t0
    return {
        "seed": seed,
        "map_filter": map_filter,
        "elapsed_sec": round(elapsed, 2),
        "participate": participate,
        "pick_plans": len(pick_plans),
        "missing": missing,
        "skip_counts": skip_counts,
        "empty_pool": len(empty_pool),
        "empty_pool_samples": empty_pool[:10],
        "warnings_tail": warnings[-5:],
    }


# --- Phase B2 extracted modules (facade re-exports) ---
from enemy_pool_filters import (  # noqa: E402
    filter_pool_for_major_boss_named_targets as filter_pool_for_cnv_special_targets,
)
from enemy_category_rules import (  # noqa: F401
    EVERGAOL_SRC_ALLOWED_TGT,
    MINOR_BOSS_SRC_ALLOWED_TGT,
    SIZE_TIER_RANK,
    _SCRIPTED_DUNGEON_BOSS_TGT,
    all_size_tier_ids,
    boss_donor_allowed_on_compact_slot,
    compact_slot_donor_block_tiers,
    compact_slot_tiers,
    dlc_trash_enabled_for_slot,
    donor_blocked_for_narrow_placement,
    donor_physique_bucket,
    dungeon_boss_arena_pick_weights,
    effective_map_kind,
    effective_slot_map_kind,
    evergaol_src_pick_weights,
    field_cavalry_mount_prefixes,
    field_cavalry_rider_prefixes,
    filter_pool_by_dlc_mode,
    filter_scripted_fog_boss_donor_indices,
    flying_model_prefixes,
    infer_category,
    infer_size_tier,
    is_boss_pool_excluded_donor,
    is_boss_pool_excluded_donor_model,
    is_cnv_named_boss_donor_template,
    is_caravan_event_slot,
    is_cnv_original_boss_slot_npc_id,
    is_dlc_enemy_map,
    is_dlc_trash_donor_model,
    is_eligible_trash_donor_model,
    is_excluded_size_tier,
    is_excluded_slot_model,
    is_excluded_slot_npc_id,
    is_field_cavalry_mount_model,
    is_field_cavalry_rider_model,
    is_horse_mount_model,
    is_humanoid_slot_allowed_donor,
    is_humanoid_slot_blocked_boss_donor,
    is_humanoid_slot_blocked_donor,
    is_hub_map_slot,
    is_invisible_enemy_model,
    is_keep_original_map_entity_slot,
    is_keep_original_slot_model,
    is_minor_boss_catalog_donor,
    is_narrow_environment_boss_slot,
    is_never_donor_hard_block_model,
    is_never_donor_model,
    is_never_donor_npc_id,
    is_night_mount_model,
    is_night_rider_model,
    is_non_participating_map,
    is_passive_animal_model,
    is_pristine_map_slot,
    is_risky_assignment,
    is_siege_c1000_operator_slot,
    is_siege_mount_rider_slot,
    is_siege_operator_slot,
    is_scripted_dungeon_main_boss_slot,
    is_trash_donor_model,
    is_unsafe_donor_template,
    load_size_tier_meta,
    map_kind,
    minor_boss_src_pick_weights,
    narrow_map_donor_block_tiers,
    narrow_map_kinds,
    narrow_map_medium_max_rank,
    is_wyvern_or_ancient_dragon_donor,
    needs_summon,
    night_model_label,
    passive_animal_model_prefixes,
    promote_cnv_named_boss_slots,
    promote_cnv_named_boss_template_categories,
    quadruped_model_prefixes,
    red_spirit_model_label,
    refine_cnv_boss_tag_slots,
    refine_cnv_boss_tag_template_categories,
    refine_cnv_new_npc_red_spirit_categories,
    refine_cnv_new_npc_red_spirit_slots,
    refine_cnv_special_template_categories,
    resolve_donor_npc_id,
    resolve_donor_origin,
    resolve_size_tier,
    resolve_src_category,
    restore_hub_map_overlays,
    scripted_dungeon_boss_pick_weights,
    should_skip_excluded_slot_tier,
    should_skip_large_slot,
    should_skip_medium_dungeon_slot,
    should_skip_zone_restricted_slot,
    size_tier_placement_aux,
    size_tier_rank,
    size_tier_rank_map,
    slot_physique_bucket,
    template_donor_map_id,
    template_is_dlc_boss_donor,
    _model_has_prefix,
)
from enemy_mount_pairs import (  # noqa: F401
    CNV_DEMOUNT_TEMPLATE_SUFFIX,
    CNV_SUPPRESS_DECORATIVE_TEMPLATE,
    CNV_SUPPRESS_MOUNT_TEMPLATE,
    MountPairDonor,
    build_global_mount_pair_pool,
    build_mount_pair_donors,
    find_mount_pair_for_rider_template,
    index_rider_mount_slot_pairs,
    mount_entity_suffix,
    mount_pair_kind_configs,
    mount_pair_kind_for_category,
    mount_pair_kind_label,
    mount_pair_pool_for_slot,
    mount_pair_randomize_enabled,
    pick_mount_pair_donor,
    skip_mount_pair_entity_when_disabled,
    slot_is_mount_pair_entity,
    slot_is_mount_pair_rider_model,
    slot_is_mount_rider_slot,
    slot_is_mounted_rider,
    template_is_mount_unit_donor,
    template_is_mounted_rider,
)
from enemy_slot_rules import (  # noqa: F401
    _assignment_to_spawn_line,
    _count_prep_skip_bucket,
    _slot_apply_collision_policy,
    _slot_placement_kind,
    augment_spawn_map_path_with_decorative_suppress,
    build_decorative_suppress_assignments,
    collect_slot_skip_rule_ids,
    describe_slot_policy,
    is_decorative_npc_slot,
    is_decorative_suppress_slot,
    is_msb_talk_slot,
    is_talk_npc_slot,
    revalidate_prep_skip_key,
    resolve_effective_slot_skip,
    runtime_slot_skip_after_prep,
    runtime_slot_skip_bucket,
    slot_has_walk_route,
)

# --- Phase B3 extracted modules (facade re-exports) ---
from enemy_donor_pick import (  # noqa: F401
    ARCHETYPE_INDEX_CACHE,
    ArchetypeIndex,
    _SlotPickPlan,
    _audit_spawn_plan_gaps,
    _pick_plans_from_prep,
    _weighted_category_try_order,
    archetype_model_counts_from_indices,
    archetype_model_counts_from_templates,
    boss_donor_template_weights,
    build_balanced_pool_donor_assignments,
    build_pool_npc_balance_weights,
    donor_pick_from_prep_index,
    drawable_category_weights,
    get_archetype_index,
    group_pool_by_archetype,
    identify_structural_tail_npcs,
    load_archetype_index,
    night_donor_template_weights,
    night_pick_mode,
    normalize_row_weights,
    pick_boss_donor_by_template_indices,
    pick_donor_by_archetype,
    pick_donor_by_archetype_indices,
    SameModelExhausted,
    _norm_model_key,
    pick_donor_model_from_bucket,
    pick_weighted_archetype_id,
    pool_pick_mode,
    pool_pick_uses_balanced_deal,
    resolve_donor_archetype_weight,
    resolve_donor_model_weight,
    resolve_night_npc_weight,
    resolve_pool_model_weight,
    resolve_trash_archetype_weights_balanced,
    resolve_trash_review_group_weight,
    same_slot_model_pick_multiplier,
    slot_rng,
    trash_archetype_pick_mode,
    trash_review_group_for_archetype,
    trash_review_group_for_model,
    trash_uniform_model_within_archetype,
    weighted_choice,
)
from enemy_contract_templates import (  # noqa: F401
    build_contract_synthetic_donor_template,
    compose_allowlist_donor_templates_by_cat,
    donor_template_chara,
    is_contract_synthetic_template,
    pick_best_donor_template,
    resolve_runtime_think,
    supplement_contract_allowlist_templates,
    supplement_dlc_boss_templates,
    supplement_dlc_trash_templates,
    supplement_synthetic_boss_templates,
)
from enemy_index_pipeline import (  # noqa: F401
    _ensure_msb_poc_built,
    build_compat_pools,
    clear_enriched_index_cache,
    compat_filter,
    enrich_index,
    load_enemy_index,
    run_index_export,
)
from enemy_rune_soul import (  # noqa: F401
    apply_radahn_phase1_think,
    apply_rune_map_scaling,
    load_gamearea_soul_maps,
    load_npc_soul_map,
    lookup_rune_amount,
    normalize_mob_drop_mode,
    raw_donor_rune_soul,
    red_spirit_rune_tier_only,
    resolve_gamearea_soul,
    tier_baseline_rune_amount,
)
from enemy_spawn_io import (  # noqa: F401
    deploy_enemy_spawn_map,
    load_map_display_names,
    load_npc_display_names,
    pin_spawn_map_for_apply,
    prune_stale_flat_sidecars,
    resolve_model_display_zh,
    write_map_spawn_audit,
    write_risk_report,
    write_spawn_map,
    write_spoiler,
    write_spoiler_zh,
)

from enemy_pool_filters import (  # noqa: F401 — facade re-export
    filter_pool_for_narrow_placement,
    filter_pool_for_scripted_fog_boss_donors,
    filter_pool_for_red_spirit_targets,
    filter_pool_for_major_boss_named_targets,
    filter_pool_for_field_boss_targets,
    filter_pool_for_night_targets,
    filter_pool_for_physique_compat,
    filter_prep_donor_indices_for_physique_compat,
    filter_pool_for_trash_targets,
    filter_pool_for_boss_target_donors,
    filter_pool_for_boss_slot_compat,
    filter_prep_donor_indices_for_slot,
    filter_pool_for_safe_donors,
    filter_pool_for_mount_compat,
    _compat_pool_for_slot_tier,
    filter_slot_donor_pool,
)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Enemy index scan / spawn map apply")
    sub = parser.add_subparsers(dest="cmd")

    scan = sub.add_parser("scan", help="Export enemy_index.json from CNV MSBs")
    scan.add_argument("--max-maps", type=int, default=None, help="Limit maps for quick test")
    scan.add_argument("--out", type=Path, default=DEFAULT_INDEX_PATH)

    apply_p = sub.add_parser("apply", help="Apply cnv_enemy_spawn_map.txt to mod/cnv_enemy overlay")
    apply_p.add_argument("--spawn-map", type=Path, default=None)
    apply_p.add_argument("--map-filter", type=str, default=None)

    prep_p = sub.add_parser("prep", help="Build enemy_slot_prep.json cache")
    prep_p.add_argument("--dlc-pool-mode", type=str, default="mixed")

    hub_p = sub.add_parser(
        "restore-hub",
        help="Delete hub MSB overlays (m11_10 / m12) so roundtable uses vanilla CNV",
    )

    mat_p = sub.add_parser(
        "materialize-prep",
        help="Expand enemy_slot_prep.json.gz to local enemy_slot_prep.json",
    )

    gen_p = sub.add_parser(
        "generate",
        help="Build spawn map + spoiler (use --map-filter for fast single-map test)",
    )
    gen_p.add_argument("--seed", type=int, default=None)
    gen_p.add_argument("--map-filter", type=str, default=None)
    gen_p.add_argument("--out-dir", type=Path, default=None)

    smoke_p = sub.add_parser(
        "smoke",
        help="Scan slots + donor pools only (no pick/write; ~4s per map, ~90s full)",
    )
    smoke_p.add_argument("--seed", type=int, default=None)
    smoke_p.add_argument("--map-filter", type=str, default=None)

    verify_p = sub.add_parser(
        "verify-bundle",
        help="Validate spawn map + T-052 sidecars (seed / copy id / donor alignment)",
    )
    verify_p.add_argument("--spawn-map", type=Path, required=True)

    args = parser.parse_args()
    if args.cmd == "generate":
        cfg = _load_json(SCRIPT_DIR / "config.json")
        out_dir = args.out_dir
        if out_dir and not out_dir.is_absolute():
            out_dir = SCRIPT_DIR / out_dir
        result = run_enemy_randomize(
            cfg,
            seed=args.seed,
            map_filter=args.map_filter,
            out_dir=out_dir,
        )
        scope = f" map={args.map_filter}" if args.map_filter else " full"
        elapsed = next(
            (
                w.split("=", 1)[1]
                for w in reversed(result.warnings)
                if str(w).startswith("用时=")
            ),
            None,
        )
        print(
            f"seed={result.seed}{scope} replaced={result.slots_replaced} "
            f"skipped={result.slots_skipped} -> {result.spawn_map_path}"
        )
        if elapsed:
            print(f"用时 {elapsed}")
    elif args.cmd == "smoke":
        cfg = _load_json(SCRIPT_DIR / "config.json")
        report = run_enemy_smoke(
            cfg,
            seed=args.seed,
            map_filter=args.map_filter,
        )
        scope = report["map_filter"] or "full"
        print(
            f"smoke seed={report['seed']} scope={scope} "
            f"elapsed={report['elapsed_sec']}s "
            f"participate={report['participate']} "
            f"pick_plans={report['pick_plans']} "
            f"missing={len(report['missing'])} "
            f"empty_pool={report['empty_pool']}"
        )
        for row in report["missing"][:15]:
            print(f"  missing {row[0]}:{row[1]} model={row[2]}")
        if len(report["missing"]) > 15:
            print(f"  ... and {len(report['missing']) - 15} more")
        for w in report["empty_pool_samples"]:
            print(f"  {w}")
    elif args.cmd == "verify-bundle":
        spawn_map = args.spawn_map
        if not spawn_map.is_absolute():
            spawn_map = SCRIPT_DIR / spawn_map
        validate_spawn_bundle(spawn_map)
        sidecars = resolve_spawn_map_sidecar_paths(spawn_map)
        header = parse_spawn_map_header(spawn_map)
        print(
            f"OK spawn={spawn_map.name} seed={header.get('seed')} "
            f"copies={sidecars['copies'].name} "
            f"npc_soul_copies={header.get('npc_soul_copies')}"
        )
    elif args.cmd == "apply":
        result = run_enemy_apply(args.spawn_map, map_filter=args.map_filter)
        print(
            f"Applied {result.slots_patched} slots across {result.maps_written} maps -> {result.overlay_dir}"
        )
        if result.hub_maps_restored:
            print(f"Hub MSB restored: {len(result.hub_maps_restored)} maps")
    elif args.cmd == "restore-hub":
        categories_cfg = _load_json(DEFAULT_CATEGORIES_PATH)
        restored = restore_hub_map_overlays(categories_cfg)
        print(f"Restored hub overlays: {len(restored)} maps")
        for mid in restored:
            print(f"  {mid}")
    elif args.cmd == "materialize-prep":
        from enemy_slot_prep import materialize_slot_prep_json

        ok = materialize_slot_prep_json(
            on_progress=lambda _p, d, t, m: print(m) if d in (0, t) else None,
        )
        if not ok:
            raise SystemExit("缺少 enemy_slot_prep.json.gz")
        print("enemy_slot_prep.json ready")
    elif args.cmd == "prep":
        from enemy_slot_prep import build_slot_prep, explain_prep_cache_miss, prep_meta

        index = load_enemy_index()
        categories_cfg = _load_json(DEFAULT_CATEGORIES_PATH)
        npc_csv_dir = Path(GAME_DIR) / "csv"
        meta = prep_meta(dlc_pool_mode=str(getattr(args, "dlc_pool_mode", "mixed")))
        miss = explain_prep_cache_miss(meta=meta)
        if miss:
            print(f"重建槽位缓存：{miss}", flush=True)
        else:
            print("强制重建槽位缓存", flush=True)

        def _prep_cli_progress(_phase: str, done: int, total: int, msg: str) -> None:
            if done in (0, total) or done % 200 == 0 or "仍在运行" in msg:
                print(msg, flush=True)

        path = build_slot_prep(
            index,
            categories_cfg,
            dlc_pool_mode=str(getattr(args, "dlc_pool_mode", "mixed")),
            npc_csv_dir=npc_csv_dir,
            on_progress=_prep_cli_progress,
        )
        print(f"Wrote {path}", flush=True)
    else:
        out = getattr(args, "out", DEFAULT_INDEX_PATH)
        max_maps = getattr(args, "max_maps", None)
        path = run_index_export(out_path=out, max_maps=max_maps)
        print(f"Wrote {path}")
