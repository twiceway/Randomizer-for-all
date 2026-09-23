#!/usr/bin/env python3
"""CNV 3.0 loot randomizer core: shuffle ItemLotParam_map + export runtime hook map."""

from __future__ import annotations

import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from paths import DEFAULT_RUNTIME_MAP, GAME_DIR, SCRIPT_DIR

CAT_WEAPON = 0
CAT_GOODS = 1
CAT_ARMOR = 2
CAT_TALISMAN = 3
CAT_ASH = 4
CAT_MAGIC = 5

CAT_NAMES = {
    CAT_WEAPON: "weapon",
    CAT_GOODS: "goods",
    CAT_ARMOR: "armor",
    CAT_TALISMAN: "talisman",
    CAT_ASH: "ash",
    CAT_MAGIC: "magic",
}

NAME_TO_CAT = {v: k for k, v in CAT_NAMES.items() if v != "goods"}

SLOT_COUNT = 8
SPOILER_RE = re.compile(
    r"^lot (\d+) slot (\d+) \[([^\]]+)\]: (\d+) -> (\d+)$"
)

# int for equipment categories; "goods/<subcat>" for goods pools
ShuffleKey = int | str

DEFAULT_SHOP_LOT_RANGES: list[tuple[int, int]] = [
    (100525, 100999),
    (101775, 101999),
    (102250, 102289),
    (102350, 102351),
    (102700, 102830),
    (122050, 122099),
    (123000, 123099),
    (129050, 129099),
    (600401, 600550),
]


@dataclass
class RandomizeResult:
    seed: int
    out_csv: Path
    patch_path: Path
    spoiler_path: Path
    runtime_map_path: Path
    stats: Counter
    spoiler_lines: list[str] = field(default_factory=list)
    runtime_pairs: int = 0
    runtime_lot_patches: int = 0
    slots_kept: int = 0
    pool_size: int = 0
    unique_pool_size: int = 0
    unique_covered: int = 0
    unique_coverage_gaps: int = 0


SHUFFLE_MODE_SLOT = "slot_shuffle"


@dataclass
class ShufflePlan:
    source_mapping: dict[int, int]
    slot_targets: dict[tuple[int, int], int]
    uncovered_uniques: list[int] = field(default_factory=list)
    shuffle_mode: str = SHUFFLE_MODE_SLOT
    multiset_size: int = 0


# Old config keys -> new fine-grained subcats
_LEGACY_GOODS_SUBCATS: dict[str, tuple[str, ...]] = {
    "quest": ("quest_key", "quest_note", "quest_unique"),
    "important": (
        "golden_seed",
        "sacred_tear",
        "larval_tear",
        "memory_stone",
        "wondrous_physick",
    ),
    "material": ("mat_animal", "mat_plant", "mat_other"),
    "upgrade_stone": (
        "stone_smithing",
        "stone_somber",
        "stone_special",
        "spirit_upgrade",
    ),
    "consumable": (
        "bolus",
        "grease",
        "pot_throw",
        "knife_throw",
        "food",
        "consumable_other",
    ),
    "rune": ("rune",),
    "spirit_ash": ("spirit_lesser", "spirit_greater"),
    "crystal_tear": ("crystal_tear",),
    "remembrance": ("remembrance", "great_rune"),
    "spell_book": ("sorcery_book", "incantation_book"),
    "throwable": ("grease", "pot_throw", "knife_throw"),
    "misc": ("misc",),
}



def _parse_enabled_goods_subcats(goods_sub: dict) -> set[str]:
    from goods_subcats import GOODS_SUBCAT_ORDER

    enabled: set[str] = set()
    for name, on in goods_sub.items():
        if not on:
            continue
        if name in GOODS_SUBCAT_ORDER:
            enabled.add(name)
        elif name in _LEGACY_GOODS_SUBCATS:
            enabled.update(_LEGACY_GOODS_SUBCATS[name])
    return enabled
def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    csv_path = Path(cfg["csv_dir"])
    if not csv_path.is_absolute():
        csv_path = (SCRIPT_DIR / csv_path).resolve()
    # Frozen release: package ships csv/; do not silently use the player's Game/csv.
    # Dev (unfrozen): allow Game/csv fallback when local relative csv/ is missing.
    if not csv_path.is_dir():
        if getattr(sys, "frozen", False):
            raise FileNotFoundError(
                "发行包缺少物品表目录 data/cnv_randomizer/csv/。"
                "请重新解压完整安装包，不要只拷贝 exe。"
            )
        from paths import try_resolve_game_dir

        game = try_resolve_game_dir()
        if game is not None:
            game_csv = (game / "csv").resolve()
            if game_csv.is_dir():
                csv_path = game_csv
    cfg["csv_dir"] = csv_path
    out_path = Path(cfg["output_dir"])
    if not out_path.is_absolute():
        out_path = (SCRIPT_DIR / out_path).resolve()
    cfg["output_dir"] = out_path
    cfg["exclude_item_ids"] = set(cfg.get("exclude_item_ids", []))
    cfg["skip_lot_ids"] = set(cfg.get("skip_lot_ids", []))
    enabled = cfg.get("randomize_categories", {})
    cfg["enabled_cats"] = {
        NAME_TO_CAT[name]
        for name, on in enabled.items()
        if on and name in NAME_TO_CAT
    }
    goods_sub = cfg.get("randomize_goods_subcats", {})
    cfg["enabled_goods_subcats"] = _parse_enabled_goods_subcats(goods_sub)
    from goods_subcats import (
        GOODS_GROUPS,
        HARD_DISABLED_GOODS_SUBCATS,
        expand_goods_groups,
        groups_from_enabled_subcats,
    )

    goods_groups = cfg.get("randomize_goods_groups", {})
    if goods_groups:
        cfg["enabled_goods_groups"] = {
            gid for gid, on in goods_groups.items() if on and gid in GOODS_GROUPS
        }
    else:
        cfg["enabled_goods_groups"] = groups_from_enabled_subcats(
            cfg["enabled_goods_subcats"]
        ) - {"quest"}
        if not cfg["enabled_goods_groups"]:
            from goods_subcats import GOODS_GROUP_PRESET_PILLAR

            cfg["enabled_goods_groups"] = set(GOODS_GROUP_PRESET_PILLAR) | {
                "important"
            }
    cfg["enabled_goods_subcats"] = expand_goods_groups(cfg["enabled_goods_groups"])
    cfg["enabled_goods_subcats"] -= HARD_DISABLED_GOODS_SUBCATS
    # 法术卢恩/骨灰/战灰跟界面「法术」开关（与审计分册一致）
    if NAME_TO_CAT.get("magic") in cfg["enabled_cats"]:
        cfg["enabled_goods_subcats"] |= {
            "spirit_lesser",
            "spirit_greater",
            "spell_rune",
        }
        cfg["enabled_cats"].add(CAT_ASH)  # 战灰并入法术
    else:
        cfg["enabled_goods_subcats"] -= {
            "spirit_lesser",
            "spirit_greater",
            "spell_rune",
        }
        cfg["enabled_cats"].discard(CAT_ASH)
    # 护符：遗物兑换，永不进池
    cfg["enabled_cats"].discard(CAT_TALISMAN)
    if cfg["enabled_goods_subcats"]:
        cfg["enabled_cats"].add(CAT_GOODS)
    ranges = cfg.get("shop_lot_ranges", DEFAULT_SHOP_LOT_RANGES)
    cfg["shop_lot_ranges"] = [(int(a), int(b)) for a, b in ranges]
    skip_ranges = cfg.get("skip_lot_ranges", [])
    cfg["skip_lot_ranges"] = [(int(a), int(b)) for a, b in skip_ranges]
    cfg["include_dlc"] = bool(cfg.get("include_dlc", True))
    cfg["region_strictness"] = max(
        0.0, min(1.0, float(cfg.get("region_strictness", 1.0)))
    )
    cfg["shuffle_mode"] = SHUFFLE_MODE_SLOT
    return cfg
def save_config(path: Path, cfg: dict) -> None:
    from goods_subcats import GOODS_GROUP_ORDER, GOODS_SUBCAT_ORDER, expand_goods_groups

    enabled = cfg.get("enabled_cats", set())
    # 写出时战灰与法术对齐；护符永不进池
    magic_on = NAME_TO_CAT.get("magic") in enabled
    randomize_categories = {
        name: (
            False
            if name == "talisman"
            else (magic_on if name == "ash" else (NAME_TO_CAT[name] in enabled))
        )
        for name in NAME_TO_CAT
    }
    enabled_groups = cfg.get("enabled_goods_groups", set())
    randomize_goods_groups = {
        gid: (gid in enabled_groups) for gid in GOODS_GROUP_ORDER
    }
    enabled_goods = expand_goods_groups(enabled_groups)
    randomize_goods_subcats = {
        name: (name in enabled_goods) for name in GOODS_SUBCAT_ORDER
    }
    out = {
        "seed": cfg.get("seed", 42001),
        "csv_dir": "../../csv",
        "output_dir": "./output/runtime",
        "target_param": cfg.get("target_param", "ItemLotParam_map"),
        "randomize_categories": randomize_categories,
        "randomize_goods_groups": randomize_goods_groups,
        "randomize_goods_subcats": randomize_goods_subcats,
        "skip_lot_ids": sorted(cfg.get("skip_lot_ids", [0, 1, 2])),
        "skip_lot_ranges": cfg.get("skip_lot_ranges", []),
        "shop_lot_ranges": [list(r) for r in cfg.get("shop_lot_ranges", DEFAULT_SHOP_LOT_RANGES)],
        "exclude_item_ids": sorted(cfg.get("exclude_item_ids", [])),
        "include_dlc": bool(cfg.get("include_dlc", True)),
        "region_strictness": round(float(cfg.get("region_strictness", 1.0)), 2),
        "shuffle_mode": cfg.get("shuffle_mode", SHUFFLE_MODE_SLOT),
        "notes": cfg.get(
            "notes",
            "Runtime hook randomizer via cnv_runtime_map.txt",
        ),
    }
    if enemy_gui := cfg.get("enemy_gui"):
        out["enemy_gui"] = enemy_gui
    maintainer = cfg.get("maintainer_gui")
    if maintainer is None and path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8-sig"))
            maintainer = existing.get("maintainer_gui")
        except (OSError, json.JSONDecodeError, TypeError):
            maintainer = None
    if maintainer is True:
        out["maintainer_gui"] = True
    try:
        out["csv_dir"] = str(Path(cfg["csv_dir"]).relative_to(SCRIPT_DIR))
    except ValueError:
        # Keep portable "csv"; frozen must use package csv only (no Game/csv fallback).
        from paths import try_resolve_game_dir

        game = try_resolve_game_dir()
        game_csv = (game / "csv").resolve() if game is not None else None
        if game_csv is not None and Path(cfg["csv_dir"]).resolve() == game_csv:
            out["csv_dir"] = "csv"
        else:
            out["csv_dir"] = str(cfg["csv_dir"])
    try:
        out["output_dir"] = str(Path(cfg["output_dir"]).relative_to(SCRIPT_DIR))
    except ValueError:
        out["output_dir"] = str(cfg["output_dir"])
    with path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
def parse_int(value: str | None) -> int:
    if value is None:
        return 0
    value = str(value).strip()
    if not value or value in {"-", "-1"}:
        return 0
    try:
        return int(float(value))
    except ValueError:
        return 0
def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        return fieldnames, list(reader)
def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
def slot_keys(index: int) -> tuple[str, str]:
    n = f"{index:02d}"
    return f"lotItemId{n}", f"lotItemCategory{n}"
def iter_slots(row: dict[str, str]):
    for i in range(1, SLOT_COUNT + 1):
        id_key, cat_key = slot_keys(i)
        yield i, id_key, cat_key, parse_int(row.get(id_key)), parse_int(row.get(cat_key))
def apply_randomization(
    rows: list[dict[str, str]],
    cfg: dict,
    unified_mapping: dict[int, int],
    type_index: dict[int, int],
    slot_targets: dict[tuple[int, int], int] | None = None,
) -> tuple[list[dict[str, str]], list[str], Counter]:
    from goods_subcats import is_spirit_ash_goods_id, spirit_ash_base_id

    out_rows: list[dict[str, str]] = []
    spoiler: list[str] = []
    stats = Counter()
    lots_touched = 0
    dlc_rules = cfg.get("dlc_rules") or load_dlc_rules()
    slot_targets = slot_targets or {}

    for row in rows:
        lot_id = parse_int(row.get("ID"))
        new_row = dict(row)
        if not lot_in_randomize_pool(row, lot_id, cfg, type_index, dlc_rules):
            out_rows.append(new_row)
            continue
        slots = lot_randomizable_slots(new_row, cfg, type_index)
        if not slots:
            out_rows.append(new_row)
            continue

        lot_changed = False
        for (
            slot_idx,
            id_key,
            cat_key,
            _csv_item_id,
            source_id,
            _true_cat,
            _shuffle_key,
        ) in slots:
            slot_key = (lot_id, slot_idx)
            if slot_key in slot_targets:
                new_id = slot_targets[slot_key]
            else:
                new_id = unified_mapping.get(source_id, source_id)
            if is_spirit_ash_goods_id(new_id):
                new_id = spirit_ash_base_id(new_id)
            if new_id == source_id:
                continue
            if not is_valid_shuffle_target(new_id, type_index, cfg):
                continue
            if new_id in cfg.get("exclude_item_ids", set()):
                continue
            new_cat = type_index.get(new_id)
            if new_cat is None:
                continue
            if not item_allowed_by_dlc(new_id, cfg, cfg.get("dlc_ranges", [])):
                continue
            new_row[id_key] = str(new_id)
            new_row[cat_key] = str(new_cat)
            target_key = resolve_shuffle_key(new_id, new_cat, cfg)
            label = (
                shuffle_key_label(target_key)
                if target_key is not None
                else CAT_NAMES.get(new_cat, str(new_cat))
            )
            spoiler.append(
                f"lot {lot_id} slot {slot_idx} [global->{label}]: {source_id} -> {new_id}"
            )
            stats[label] += 1
            lot_changed = True

        if lot_changed:
            lots_touched += 1
        out_rows.append(new_row)

    stats["lots"] = lots_touched
    return out_rows, spoiler, stats
def write_massedit_patch(
    path: Path,
    rows_before: list[dict[str, str]],
    rows_after: list[dict[str, str]],
    cfg: dict,
    type_index: dict[int, int],
) -> int:
    lines: list[str] = []
    before_by_id = {parse_int(r.get("ID")): r for r in rows_before}
    for row in rows_after:
        lot_id = parse_int(row.get("ID"))
        if not is_randomizable_lot(lot_id, cfg):
            continue
        old = before_by_id.get(lot_id)
        if old is None:
            continue
        for slot_idx, id_key, cat_key, _, _, _, _ in lot_randomizable_slots(
            row, cfg, type_index
        ):
            if row.get(id_key) != old.get(id_key) or row.get(cat_key) != old.get(cat_key):
                lines.append(
                    f"param ItemLotParam_map: id {lot_id}: {id_key}: = {row.get(id_key)};"
                )
                lines.append(
                    f"param ItemLotParam_map: id {lot_id}: {cat_key}: = {row.get(cat_key)};"
                )
    if lines:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)
def build_lot_patches_from_slot_targets(
    slot_targets: dict[tuple[int, int], int],
    type_index: dict[int, int],
    cfg: dict,
    rows: list[dict[str, str]] | None = None,
) -> list[tuple[int, int, int, int, int]]:
    """One patch per (lot, slot) from the shuffle plan — no global target dedupe."""
    from goods_subcats import (
        is_gathering_lot_id,
        is_gathering_material_id,
        is_goods_hard_excluded,
        is_spell_rune_crush_lot,
        is_spirit_ash_goods_id,
        spirit_ash_base_id,
        spell_rune_shuffle_enabled,
    )
    from lot_effective import resolve_slot_source_item

    effective_map = cfg.get("lot_effective_items", {})
    goods_rows = cfg.get("goods_rows", {})
    csv_by_lot: dict[int, dict[str, str]] = {}
    if rows:
        csv_by_lot = {parse_int(r.get("ID")): r for r in rows}

    patches: list[tuple[int, int, int, int, int]] = []
    for (lot_id, slot_idx), new_id in sorted(slot_targets.items()):
        if is_gathering_lot_id(lot_id):
            continue
        if is_spell_rune_crush_lot(lot_id) and not spell_rune_shuffle_enabled(cfg):
            continue
        if is_spirit_ash_goods_id(new_id):
            new_id = spirit_ash_base_id(new_id)
        if new_id <= 0 or is_goods_hard_excluded(new_id):
            continue
        if is_gathering_material_id(new_id):
            continue
        if not is_valid_shuffle_target(new_id, type_index, cfg):
            continue
        target_cat = type_index.get(new_id, CAT_WEAPON)
        runtime_source = 0
        row = csv_by_lot.get(lot_id)
        if row:
            for s_idx, _id_key, _cat_key, csv_id, _lot_cat in iter_slots(row):
                if s_idx != slot_idx:
                    continue
                effective = resolve_slot_source_item(
                    lot_id, slot_idx, csv_id, effective_map
                )
                if effective != csv_id:
                    runtime_source = effective
                break
        patches.append((lot_id, slot_idx, new_id, target_cat, runtime_source))
    return patches
def write_runtime_map(
    path: Path,
    seed: int,
    lot_patches: list[tuple[int, int, int, int] | tuple[int, int, int, int, int]]
    | None = None,
    *,
    lot_patch: int = 0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lot_patches = lot_patches or []
    lines = [
        "# CNV runtime pickup map — used by mod/dll/cnv_pickup_hook.dll",
        f"seed={seed}",
        f"lot_patch={len(lot_patches) if lot_patches else lot_patch}",
        "# lot remap: lot lot_id slot target_raw_id target_category [runtime_source]",
    ]
    for entry in sorted(lot_patches):
        if len(entry) >= 5:
            lot_id, slot, target, target_cat, runtime_source = entry[:5]
            if runtime_source > 0:
                lines.append(
                    f"lot {lot_id} {slot} {target} {target_cat} {runtime_source}"
                )
            else:
                lines.append(f"lot {lot_id} {slot} {target} {target_cat}")
        else:
            lot_id, slot, target, target_cat = entry
            lines.append(f"lot {lot_id} {slot} {target} {target_cat}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
def deploy_runtime_map(
    src: Path,
    dest: Path | None = None,
) -> Path:
    dest_path = Path(dest) if dest is not None else Path(DEFAULT_RUNTIME_MAP)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dest_path

from pickup_pool import (
    build_unified_pool,
    classify_item,
    count_kept_slots,
    is_dlc_item,
    is_dlc_lot,
    is_randomizable_lot,
    is_shop_lot,
    is_skipped_lot,
    is_valid_shuffle_target,
    item_allowed_by_dlc,
    load_dlc_item_rules,
    load_dlc_rules,
    load_goods_ids,
    load_item_type_index,
    lot_in_randomize_pool,
    lot_randomizable_slots,
    resolve_item_category,
    resolve_shuffle_key,
    shuffle_key_enabled,
    shuffle_key_label,
)
from pickup_shuffle import (
    build_region_context,
    build_region_panel_cache,
    build_region_panel_data,
    build_shuffle_plan,
    build_slot_shuffle_plan,
    build_tier_context,
    collect_mapping_sources,
    collect_randomizable_slots,
    collect_randomizable_slots_from_pickup_index,
    compute_effective_pools,
    count_items_by_tier,
    count_slots_by_tier,
    RegionPanelCache,
    should_use_pickup_slot_index,
    _lot_to_region_from_pickup_index,
    _rows_by_lot_id,
)

_PICKUP_CSV_BUNDLE_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def _pickup_csv_bundle_key(csv_dir: Path) -> tuple[Any, ...]:
    resolved = str(csv_dir.resolve())
    parts: list[tuple[str, int, int]] = []
    for name in (
        "ItemLotParam_map.csv",
        "GoodsParam.csv",
        "WeaponParam.csv",
        "ProtectorParam.csv",
        "AccessoryParam.csv",
        "GemParam.csv",
    ):
        path = csv_dir / name
        if path.is_file():
            st = path.stat()
            parts.append((name, st.st_size, int(st.st_mtime_ns)))
        else:
            parts.append((name, 0, 0))
    return (resolved, tuple(parts))


def _load_pickup_csv_bundle(csv_dir: Path) -> dict[str, Any]:
    key = _pickup_csv_bundle_key(csv_dir)
    hit = _PICKUP_CSV_BUNDLE_CACHE.get(key)
    if hit is not None:
        return hit
    from goods_subcats import (
        load_accessory_rows,
        load_gem_rows,
        load_goods_rows,
        load_goods_subcat_index,
        load_protector_rows,
        load_weapon_rows,
    )
    from lot_effective import load_lot_effective_items

    bundle = {
        "goods_rows": load_goods_rows(csv_dir),
        "goods_subcat_index": load_goods_subcat_index(csv_dir),
        "weapon_rows": load_weapon_rows(csv_dir),
        "accessory_rows": load_accessory_rows(csv_dir),
        "protector_rows": load_protector_rows(csv_dir),
        "gem_rows": load_gem_rows(csv_dir),
        "lot_effective_items": load_lot_effective_items(),
        "type_index": load_item_type_index(csv_dir),
    }
    _PICKUP_CSV_BUNDLE_CACHE[key] = bundle
    return bundle


def run_randomize(
    cfg: dict,
    *,
    runtime_map_path: Path | None = None,
    deploy: bool = False,
) -> RandomizeResult:
    src_name = f"{cfg['target_param']}.csv"
    csv_dir = Path(cfg["csv_dir"])
    src_path = csv_dir / src_name
    if not src_path.exists():
        raise FileNotFoundError(f"Missing CSV: {src_path}")

    cfg["dlc_rules"] = load_dlc_rules()
    cfg["dlc_ranges"] = cfg["dlc_rules"]["item_ranges"]
    from goods_subcats import is_goods_hard_excluded

    csv_bundle = _load_pickup_csv_bundle(csv_dir)
    goods_rows = csv_bundle["goods_rows"]
    goods_subcat_index = csv_bundle["goods_subcat_index"]
    cfg["goods_rows"] = goods_rows
    cfg["goods_subcat_index"] = goods_subcat_index
    cfg["weapon_rows"] = csv_bundle["weapon_rows"]
    cfg["accessory_rows"] = csv_bundle["accessory_rows"]
    cfg["protector_rows"] = csv_bundle["protector_rows"]
    cfg["gem_rows"] = csv_bundle["gem_rows"]
    cfg["lot_effective_items"] = csv_bundle["lot_effective_items"]

    cfg["exclude_item_ids"] = set(cfg.get("exclude_item_ids", []))
    for item_id in goods_rows:
        if is_goods_hard_excluded(item_id):
            cfg["exclude_item_ids"].add(item_id)

    from category_switch_pool import apply_category_switch_pool_to_cfg

    apply_category_switch_pool_to_cfg(cfg)

    fieldnames, rows = read_csv(src_path)
    type_index = csv_bundle["type_index"]
    slots_kept = count_kept_slots(rows, cfg, type_index)
    unified_pool = build_unified_pool(rows, cfg, type_index)
    cfg["shuffle_target_pool"] = set(unified_pool)
    sources = collect_mapping_sources(rows, cfg, type_index)
    tier_slot_counts = count_slots_by_tier(rows, cfg, type_index, unified_pool)
    region_slot_counts, _local, _eff, region_pool_count = build_region_panel_data(
        rows, cfg, type_index, unified_pool
    )
    seed = int(cfg["seed"])
    plan = build_shuffle_plan(
        rows, sources, unified_pool, seed, cfg, type_index
    )
    from goods_subcats import is_unique_pool_item

    unique_pool_set = {
        p for p in unified_pool if is_unique_pool_item(p, type_index, cfg)
    }
    unique_pool_size = len(unique_pool_set)
    out_rows, spoiler_lines, stats = apply_randomization(
        rows, cfg, plan.source_mapping, type_index, plan.slot_targets
    )
    unique_targets = {
        int(m.group(5))
        for line in spoiler_lines
        if (m := SPOILER_RE.match(line.strip()))
    }
    unique_covered = len(unique_targets & unique_pool_set)

    out_dir = Path(cfg["output_dir"])
    out_csv = out_dir / src_name
    write_csv(out_csv, fieldnames, out_rows)

    patch_path = out_dir / "ItemLotParam_map.massedit"
    patch_lines = write_massedit_patch(patch_path, rows, out_rows, cfg, type_index)

    ts = datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    summary = [
        f"seed={seed}",
        f"shuffle_mode={plan.shuffle_mode}",
        f"shuffle_multiset_size={plan.multiset_size}",
        f"region_strictness={cfg.get('region_strictness', 1.0)}",
        f"global_pool_size={len(unified_pool)}",
        f"unique_pool_size={unique_pool_size}",
        f"unique_covered={unique_covered}",
        f"unique_coverage_gaps={len(plan.uncovered_uniques)}",
        f"mapping_sources={len(sources)}",
        f"slot_assignments={len(plan.slot_targets)}",
        f"randomizable_slots={sum(tier_slot_counts.values())}",
        "tier_slots="
        + ", ".join(
            f"{tier}:{tier_slot_counts.get(tier, 0)}"
            for tier in sorted(tier_slot_counts)
        ),
        f"region_pools={region_pool_count}",
        f"region_slots={sum(region_slot_counts.values())}",
        f"include_dlc={'yes' if cfg.get('include_dlc', True) else 'no'}",
        f"changed_slots={sum(v for k, v in stats.items() if k != 'lots')}",
        f"changed_lots={stats.get('lots', 0)}",
        f"kept_slots={slots_kept}",
        "by_target="
        + ", ".join(f"{k}:{v}" for k, v in sorted(stats.items()) if k != "lots"),
        f"massedit_lines={patch_lines}",
    ]
    spoiler_path = out_dir / f"spoiler_{seed}_{ts}.txt"
    spoiler_path.write_text("\n".join(spoiler_lines + summary) + "\n", encoding="utf-8")

    lot_patches = build_lot_patches_from_slot_targets(
        plan.slot_targets, type_index, cfg, rows
    )
    runtime_map_path = runtime_map_path or (out_dir / "cnv_runtime_map.txt")
    write_runtime_map(runtime_map_path, seed, lot_patches)

    if deploy:
        deploy_runtime_map(runtime_map_path)

    return RandomizeResult(
        seed=seed,
        out_csv=out_csv,
        patch_path=patch_path,
        spoiler_path=spoiler_path,
        runtime_map_path=runtime_map_path,
        stats=stats,
        spoiler_lines=spoiler_lines,
        runtime_pairs=0,
        runtime_lot_patches=len(lot_patches),
        slots_kept=slots_kept,
        pool_size=len(unified_pool),
        unique_pool_size=unique_pool_size,
        unique_covered=unique_covered,
        unique_coverage_gaps=len(plan.uncovered_uniques),
    )
def _prepare_pickup_cfg(cfg: dict) -> dict:
    cfg = dict(cfg)
    cfg["dlc_rules"] = load_dlc_rules()
    cfg["dlc_ranges"] = cfg["dlc_rules"]["item_ranges"]
    from goods_subcats import (
        load_accessory_rows,
        load_gem_rows,
        load_goods_rows,
        load_goods_subcat_index,
        load_protector_rows,
        load_weapon_rows,
    )

    csv_dir = Path(cfg["csv_dir"])
    goods_rows = load_goods_rows(csv_dir)
    cfg["goods_rows"] = goods_rows
    cfg["goods_subcat_index"] = load_goods_subcat_index(csv_dir)
    cfg["weapon_rows"] = load_weapon_rows(csv_dir)
    cfg["accessory_rows"] = load_accessory_rows(csv_dir)
    cfg["protector_rows"] = load_protector_rows(csv_dir)
    cfg["gem_rows"] = load_gem_rows(csv_dir)
    from lot_effective import load_lot_effective_items

    cfg["lot_effective_items"] = load_lot_effective_items()
    from goods_subcats import is_goods_hard_excluded

    cfg["exclude_item_ids"] = set(cfg.get("exclude_item_ids", []))
    for item_id in goods_rows:
        if is_goods_hard_excluded(item_id):
            cfg["exclude_item_ids"].add(item_id)
    from category_switch_pool import apply_category_switch_pool_to_cfg

    apply_category_switch_pool_to_cfg(cfg)
    return cfg
def run_pickup_smoke(seed: int = 42, map_filter: str | None = None) -> dict:
    """Single-map pickup shuffle smoke: placements · slots · multiset conservation."""
    from pickup_slot_index import (
        DEFAULT_PICKUP_INDEX_PATH,
        load_pickup_slot_index,
        placements_for_map,
    )

    cfg = _prepare_pickup_cfg(load_config(SCRIPT_DIR / "config.json"))
    cfg["seed"] = int(seed)
    src_path = Path(cfg["csv_dir"]) / f"{cfg['target_param']}.csv"
    _, rows = read_csv(src_path)
    type_index = load_item_type_index(Path(cfg["csv_dir"]))
    unified_pool = build_unified_pool(rows, cfg, type_index)
    cfg["shuffle_target_pool"] = set(unified_pool)
    index = load_pickup_slot_index(
        Path(cfg.get("pickup_slot_index_path", DEFAULT_PICKUP_INDEX_PATH))
    )
    placements = placements_for_map(index or {}, map_filter)
    placement_lot_ids = {
        int(p.get("lot_id", 0) or 0) for p in placements if int(p.get("lot_id", 0) or 0) > 0
    }

    all_slots = collect_randomizable_slots(rows, cfg, type_index)
    if map_filter:
        all_slots = [s for s in all_slots if s[0] in placement_lot_ids]

    item_pool = {src for _lot_id, _slot_idx, src in all_slots}
    lot_regions, item_regions, lot_tiers, item_tiers = build_region_context(
        rows, cfg, type_index, item_pool
    )
    plan = build_slot_shuffle_plan(rows, seed, cfg, type_index)

    by_region: dict[str, list[tuple[int, int, int]]] = {}
    if should_use_pickup_slot_index(cfg) and index:
        rows_by_lot = _rows_by_lot_id(rows)
        lot_to_region = _lot_to_region_from_pickup_index(
            index.get("placements") or [], rows_by_lot, cfg, lot_regions
        )
        for lot_id, slot_idx, src in all_slots:
            region = lot_to_region.get(lot_id, lot_regions.get(lot_id, "T5"))
            by_region.setdefault(region, []).append((lot_id, slot_idx, src))
    else:
        for lot_id, slot_idx, src in all_slots:
            region = lot_regions.get(lot_id, "T5")
            by_region.setdefault(region, []).append((lot_id, slot_idx, src))

    multiset_ok = True
    region_reports: list[dict] = []
    from goods_subcats import is_golden_rune_item

    rune_src = 0
    rune_changed_non_rune = 0
    for region, region_slots in sorted(by_region.items()):
        # 非黄金卢恩源：区内 multiset 仍须守恒；卢恩源抽分类开关池，不计入
        non_rune_slots = [
            (lot, slot, src)
            for lot, slot, src in region_slots
            if not is_golden_rune_item(src)
        ]
        src_counter = Counter(src for _lot, _slot, src in non_rune_slots)
        tgt_counter: Counter = Counter()
        for lot_id, slot_idx, src in non_rune_slots:
            tgt = plan.slot_targets.get((lot_id, slot_idx), src)
            tgt_counter[tgt] += 1
        ok = src_counter == tgt_counter
        multiset_ok = multiset_ok and ok
        for lot_id, slot_idx, src in region_slots:
            if not is_golden_rune_item(src):
                continue
            rune_src += 1
            tgt = plan.slot_targets.get((lot_id, slot_idx), src)
            if tgt != src and not is_golden_rune_item(tgt):
                rune_changed_non_rune += 1
        region_reports.append(
            {
                "region": region,
                "slots": len(region_slots),
                "multiset_ok": ok,
            }
        )

    scoped_targets = sum(
        1 for lot_id, slot_idx, _src in all_slots if (lot_id, slot_idx) in plan.slot_targets
    )
    return {
        "seed": seed,
        "map_filter": map_filter,
        "index_placements": len(placements),
        "placement_lot_ids": len(placement_lot_ids),
        "shuffle_slots": len(all_slots),
        "slot_targets": scoped_targets,
        "slot_targets_global": len(plan.slot_targets),
        "multiset_ok": multiset_ok,
        "rune_sources": rune_src,
        "rune_to_non_rune": rune_changed_non_rune,
        "regions": region_reports,
        "use_pickup_index": should_use_pickup_slot_index(cfg),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CNV pickup randomizer CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    export_p = sub.add_parser("pickup-index-export", help="Scan MSB treasures → pickup_slot_index.json")
    export_p.add_argument("--out", type=str, default=None)

    smoke_p = sub.add_parser("pickup-smoke", help="Smoke test slot_shuffle on one map")
    smoke_p.add_argument("--seed", type=int, default=42)
    smoke_p.add_argument("--map-filter", type=str, default=None)

    args = parser.parse_args()
    if args.cmd == "pickup-index-export":
        from pickup_slot_index import DEFAULT_PICKUP_INDEX_PATH, run_pickup_index_export

        out = Path(args.out) if args.out else DEFAULT_PICKUP_INDEX_PATH
        path = run_pickup_index_export(out_path=out)
        print(f"Wrote {path}")
    elif args.cmd == "pickup-smoke":
        report = run_pickup_smoke(seed=args.seed, map_filter=args.map_filter)
        scope = report["map_filter"] or "all"
        print(
            f"pickup-smoke seed={report['seed']} scope={scope} "
            f"index={report['use_pickup_index']} "
            f"placements={report['index_placements']} "
            f"slots={report['shuffle_slots']} "
            f"targets={report['slot_targets']} "
            f"multiset_ok={report['multiset_ok']} "
            f"rune_src={report.get('rune_sources', 0)} "
            f"rune_to_item={report.get('rune_to_non_rune', 0)}"
        )
        for row in report["regions"]:
            print(
                f"  {row['region']}: slots={row['slots']} multiset_ok={row['multiset_ok']}"
            )

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CNV pickup randomizer CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    export_p = sub.add_parser("pickup-index-export", help="Scan MSB treasures → pickup_slot_index.json")
    export_p.add_argument("--out", type=str, default=None)

    smoke_p = sub.add_parser("pickup-smoke", help="Smoke test slot_shuffle on one map")
    smoke_p.add_argument("--seed", type=int, default=42)
    smoke_p.add_argument("--map-filter", type=str, default=None)

    args = parser.parse_args()
    if args.cmd == "pickup-index-export":
        from pickup_slot_index import DEFAULT_PICKUP_INDEX_PATH, run_pickup_index_export

        out = Path(args.out) if args.out else DEFAULT_PICKUP_INDEX_PATH
        path = run_pickup_index_export(out_path=out)
        print(f"Wrote {path}")
    elif args.cmd == "pickup-smoke":
        report = run_pickup_smoke(seed=args.seed, map_filter=args.map_filter)
        scope = report["map_filter"] or "all"
        print(
            f"pickup-smoke seed={report['seed']} scope={scope} "
            f"index={report['use_pickup_index']} "
            f"placements={report['index_placements']} "
            f"slots={report['shuffle_slots']} "
            f"targets={report['slot_targets']} "
            f"multiset_ok={report['multiset_ok']} "
            f"rune_src={report.get('rune_sources', 0)} "
            f"rune_to_item={report.get('rune_to_non_rune', 0)}"
        )
        for row in report["regions"]:
            print(
                f"  {row['region']}: slots={row['slots']} multiset_ok={row['multiset_ok']}"
            )
