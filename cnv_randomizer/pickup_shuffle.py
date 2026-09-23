import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from cnv_randomizer_core import SHUFFLE_MODE_SLOT, ShufflePlan, iter_slots, parse_int
from paths import SCRIPT_DIR
from pickup_pool import (
    is_randomizable_lot,
    is_valid_shuffle_target,
    load_dlc_rules,
    lot_in_randomize_pool,
    lot_randomizable_slots,
)

@dataclass
class RegionPanelCache:
    """Static region panel inputs; effective pools depend only on region_strictness."""

    rows_data: list[tuple[str, int, int]]
    pool_size: int
    region_lot_tier: dict[str, int]
    pool: set[int]
    item_regions: dict[int, str]
    item_tiers: dict[int, int]

def should_use_pickup_slot_index(cfg: dict) -> bool:
    if not cfg.get("use_pickup_slot_index", True):
        return False
    from pickup_slot_index import DEFAULT_PICKUP_INDEX_PATH, load_pickup_slot_index

    path = Path(cfg.get("pickup_slot_index_path", DEFAULT_PICKUP_INDEX_PATH))
    return load_pickup_slot_index(path) is not None

def _rows_by_lot_id(rows: list[dict[str, str]]) -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {}
    for row in rows:
        lot_id = parse_int(row.get("ID"))
        if lot_id > 0:
            out[lot_id] = row
    return out

def _lot_slot_source_item(
    lot_id: int,
    slot_idx: int,
    csv_item_id: int,
    cfg: dict,
) -> int:
    from lot_effective import resolve_slot_source_item

    effective_map = cfg.get("lot_effective_items", {})
    return resolve_slot_source_item(lot_id, slot_idx, csv_item_id, effective_map)

def _lot_to_region_from_pickup_index(
    placements: list[dict],
    rows_by_lot: dict[int, dict[str, str]],
    cfg: dict,
    lot_regions: dict[int, str] | None = None,
) -> dict[int, str]:
    from pickup_slot_index import resolve_placement_region_key

    lot_to_region: dict[int, str] = {}
    ordered = sorted(
        placements,
        key=lambda p: (str(p.get("map_id", "")), int(p.get("lot_id", 0) or 0)),
    )
    for placement in ordered:
        map_id = str(placement.get("map_id", ""))
        lot_id = int(placement.get("lot_id", 0) or 0)
        if lot_id <= 0 or lot_id in lot_to_region:
            continue
        row = rows_by_lot.get(lot_id)
        if not row:
            continue
        lot_to_region[lot_id] = resolve_placement_region_key(
            map_id, lot_id, row, cfg, lot_regions
        )
    return lot_to_region

def _indexed_lot_ids(cfg: dict) -> set[int]:
    from pickup_slot_index import DEFAULT_PICKUP_INDEX_PATH, load_pickup_slot_index

    path = Path(cfg.get("pickup_slot_index_path", DEFAULT_PICKUP_INDEX_PATH))
    index = load_pickup_slot_index(path)
    if not index:
        return set()
    out: set[int] = set()
    for placement in index.get("placements") or []:
        lot_id = int(placement.get("lot_id", 0) or 0)
        if lot_id > 0:
            out.add(lot_id)
    return out


def _lot_name_looks_boss_reward(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return False
    # Crush/grant tables look like \"Tome #1 - Bestial - Beast Talons\" — not world pickups.
    if n.lower().startswith("tome #"):
        return False
    low = n.lower()
    keys = (
        "boss",
        "remembrance",
        "evergaol",
        "hero's grave",
        "heros grave",
        "catacombs",
        " cemetery",
        "watchdog",
        "ulcerated",
        "godskin",
        "tree spirit",
        "deathrite",
        "putrid",
        "cleanrot",
        "crucible knight",
        "night's cavalry",
        "deathbird",
        "erdtree avatar",
        "fallingstar",
        "magna wyrm",
        "dragonkin",
        "ancestor spirit",
        "mimic tear",
        "valiant gargoyle",
        "fortissax",
        "placidusax",
        "malenia",
        "radahn",
        "morgott",
        "mohg",
        "rykard",
        "godfrey",
        "hoarah",
        "elden beast",
        "radagon",
        "rennala",
        "ranni",
        "astel",
        "fire giant",
        "loretta",
        "commander",
        "field boss",
        "post boss",
    )
    return any(k in low for k in keys)


def _lot_name_looks_teardrop_scarab(name: str) -> bool:
    """CNV 战灰圣甲虫掉落挂在 ItemLotParam_map，名含 Teardrop Scarab。"""
    n = name or ""
    return "Teardrop Scarab" in n or "Ash of War Scarab" in n


def _goods_display_names(cfg: dict) -> tuple[dict[int, str], dict[int, str]]:
    """中文 / 英文道具显示名（懒加载进 cfg）。"""
    zh = cfg.get("goods_name_zh")
    en = cfg.get("goods_name_en")
    if isinstance(zh, dict) and isinstance(en, dict):
        return zh, en
    zh_map: dict[int, str] = {}
    en_map: dict[int, str] = {}
    try:
        zh_path = SCRIPT_DIR / "cache" / "item_names_zhocn_dlc02.json"
        en_path = SCRIPT_DIR / "cache" / "item_names_engus_dlc02.json"
        if zh_path.is_file():
            raw = json.loads(zh_path.read_text(encoding="utf-8-sig"))
            block = raw.get("GoodsName.fmg") or {}
            for k, v in block.items():
                try:
                    zh_map[int(k)] = str(v or "")
                except (TypeError, ValueError):
                    continue
            for key in ("GoodsName_dlc01.fmg", "GoodsName_dlc02.fmg"):
                for k, v in (raw.get(key) or {}).items():
                    try:
                        iid = int(k)
                    except (TypeError, ValueError):
                        continue
                    if iid not in zh_map and v:
                        zh_map[iid] = str(v)
        if en_path.is_file():
            raw = json.loads(en_path.read_text(encoding="utf-8-sig"))
            block = raw.get("GoodsName.fmg") or {}
            for k, v in block.items():
                try:
                    en_map[int(k)] = str(v or "")
                except (TypeError, ValueError):
                    continue
    except OSError:
        pass
    cfg["goods_name_zh"] = zh_map
    cfg["goods_name_en"] = en_map
    return zh_map, en_map


def _lot_drops_relic_goods(row: dict[str, str], cfg: dict) -> bool:
    """中文名含「遗物」或英文 Remnant/Relic 的道具。"""
    zh, en = _goods_display_names(cfg)
    goods_rows = cfg.get("goods_rows") or {}
    for _slot_idx, _id_key, _cat_key, item_id, _lot_cat in iter_slots(row):
        if item_id <= 0:
            continue
        name_zh = zh.get(item_id) or ""
        if "遗物" in name_zh:
            return True
        name_en = en.get(item_id) or str((goods_rows.get(item_id) or {}).get("Name") or "")
        low = name_en.lower()
        if "remnant" in low or "relic" in low:
            return True
    return False


def _lot_eligible_for_map_inject(name: str, row: dict[str, str], cfg: dict) -> bool:
    """Boss 固定奖 + 泪滴圣甲虫 + 未索引遗物 ton。"""
    if _lot_has_spell_rune_or_teach_book(row, cfg):
        return True
    if _lot_name_looks_boss_reward(name):
        return True
    if _lot_name_looks_teardrop_scarab(name):
        return True
    if _lot_drops_relic_goods(row, cfg):
        return True
    return False


def _lot_has_spell_rune_or_teach_book(row: dict[str, str], cfg: dict) -> bool:
    from goods_subcats import is_spell_rune_item, is_spell_teach_book_item

    goods_rows = cfg.get("goods_rows", {})
    for _slot_idx, _id_key, _cat_key, item_id, _lot_cat in iter_slots(row):
        if item_id <= 0:
            continue
        if is_spell_rune_item(item_id, goods_rows.get(item_id)):
            return True
        if is_spell_teach_book_item(item_id):
            return True
    return False


def collect_boss_reward_map_lots(
    rows: list[dict[str, str]],
    cfg: dict,
    type_index: dict[int, int],
    indexed_lot_ids: set[int] | None = None,
) -> list[tuple[int, int, int]]:
    """Boss/fog + 泪滴圣甲虫 + 漏遗物 map lots not on MSB treasure index."""
    # Hard rule: callers must pass ItemLotParam_map rows only.
    if cfg.get("target_param", "ItemLotParam_map") != "ItemLotParam_map":
        raise RuntimeError("boss reward inject only allows ItemLotParam_map")

    indexed = indexed_lot_ids if indexed_lot_ids is not None else _indexed_lot_ids(cfg)
    dlc_rules = cfg.get("dlc_rules") or load_dlc_rules()
    slots: list[tuple[int, int, int]] = []
    for row in rows:
        lot_id = parse_int(row.get("ID"))
        if lot_id <= 0 or lot_id in indexed:
            continue
        name = row.get("Name") or row.get("name") or ""
        if not _lot_eligible_for_map_inject(name, row, cfg):
            continue
        if not lot_in_randomize_pool(row, lot_id, cfg, type_index, dlc_rules):
            continue
        for slot_idx, _id_key, _cat_key, csv_id, _item_id, _true_cat, _shuffle_key in (
            lot_randomizable_slots(row, cfg, type_index)
        ):
            source_id = _lot_slot_source_item(lot_id, slot_idx, csv_id, cfg)
            slots.append((lot_id, slot_idx, source_id))
    return slots


def collect_randomizable_slots_from_pickup_index(
    rows: list[dict[str, str]],
    cfg: dict,
    type_index: dict[int, int],
    lot_regions: dict[int, str] | None = None,
) -> list[tuple[int, int, int]]:
    from pickup_slot_index import DEFAULT_PICKUP_INDEX_PATH, load_pickup_slot_index

    path = Path(cfg.get("pickup_slot_index_path", DEFAULT_PICKUP_INDEX_PATH))
    index = load_pickup_slot_index(path)
    if not index:
        return []

    placements = index.get("placements") or []
    rows_by_lot = _rows_by_lot_id(rows)
    lot_to_region = _lot_to_region_from_pickup_index(
        placements, rows_by_lot, cfg, lot_regions
    )
    dlc_rules = cfg.get("dlc_rules") or load_dlc_rules()
    slots: list[tuple[int, int, int]] = []
    for lot_id, region_key in sorted(lot_to_region.items(), key=lambda x: (x[1], x[0])):
        row = rows_by_lot.get(lot_id)
        if not row:
            continue
        if not lot_in_randomize_pool(row, lot_id, cfg, type_index, dlc_rules):
            continue
        for slot_idx, _id_key, _cat_key, csv_id, _item_id, _true_cat, _shuffle_key in (
            lot_randomizable_slots(row, cfg, type_index)
        ):
            source_id = _lot_slot_source_item(lot_id, slot_idx, csv_id, cfg)
            slots.append((lot_id, slot_idx, source_id))
        _ = region_key
    return slots

def collect_randomizable_slots(
    rows: list[dict[str, str]], cfg: dict, type_index: dict[int, int]
) -> list[tuple[int, int, int]]:
    """(lot_id, slot_index, source_item_id) for each randomizable pickup slot."""
    if cfg.get("target_param", "ItemLotParam_map") == "ItemLotParam_enemy":
        raise RuntimeError("item shuffle must not read ItemLotParam_enemy")

    if should_use_pickup_slot_index(cfg):
        indexed = collect_randomizable_slots_from_pickup_index(rows, cfg, type_index)
        if indexed:
            indexed_ids = {lot_id for lot_id, _s, _i in indexed}
            boss = collect_boss_reward_map_lots(rows, cfg, type_index, indexed_ids)
            # Dedup by (lot, slot)
            seen = {(lot_id, slot_idx) for lot_id, slot_idx, _ in indexed}
            merged = list(indexed)
            for lot_id, slot_idx, source_id in boss:
                key = (lot_id, slot_idx)
                if key in seen:
                    continue
                seen.add(key)
                merged.append((lot_id, slot_idx, source_id))
            return merged
    dlc_rules = cfg.get("dlc_rules") or load_dlc_rules()
    slots: list[tuple[int, int, int]] = []
    for row in rows:
        lot_id = parse_int(row.get("ID"))
        if not lot_in_randomize_pool(row, lot_id, cfg, type_index, dlc_rules):
            continue
        for slot_idx, _id_key, _cat_key, csv_id, _item_id, _true_cat, _shuffle_key in (
            lot_randomizable_slots(row, cfg, type_index)
        ):
            source_id = _lot_slot_source_item(lot_id, slot_idx, csv_id, cfg)
            slots.append((lot_id, slot_idx, source_id))
    return slots

def count_slots_by_tier(
    rows: list[dict[str, str]],
    cfg: dict,
    type_index: dict[int, int],
    pool: set[int],
) -> Counter:
    lot_tiers, _item_tiers = build_tier_context(rows, cfg, type_index, pool)
    dlc_rules = cfg.get("dlc_rules") or load_dlc_rules()
    counts: Counter = Counter()
    for row in rows:
        lot_id = parse_int(row.get("ID"))
        if not lot_in_randomize_pool(row, lot_id, cfg, type_index, dlc_rules):
            continue
        tier = lot_tiers.get(lot_id, 5)
        for _ in lot_randomizable_slots(row, cfg, type_index):
            counts[tier] += 1
    return counts

def count_items_by_tier(
    pool: set[int],
    item_tiers: dict[int, int],
) -> Counter:
    counts: Counter = Counter()
    for item_id in pool:
        counts[item_tiers.get(item_id, 5)] += 1
    return counts

def collect_mapping_sources(
    rows: list[dict[str, str]], cfg: dict, type_index: dict[int, int]
) -> set[int]:
    """Unique source item ids whose pickups should roll from the global pool."""
    dlc_rules = cfg.get("dlc_rules") or load_dlc_rules()
    sources: set[int] = set()
    for row in rows:
        lot_id = parse_int(row.get("ID"))
        if not lot_in_randomize_pool(row, lot_id, cfg, type_index, dlc_rules):
            continue
        for *_, item_id, _true_cat, _shuffle_key in lot_randomizable_slots(
            row, cfg, type_index
        ):
            sources.add(item_id)
    return sources

def build_region_context(
    rows: list[dict[str, str]],
    cfg: dict,
    type_index: dict[int, int],
    pool: set[int],
) -> tuple[dict[int, str], dict[int, str], dict[int, int], dict[int, int]]:
    from region_tiers import (
        build_item_region_index,
        build_item_tier_index,
        build_lot_region_index,
        build_lot_tier_index,
    )

    lot_tiers = build_lot_tier_index(rows, cfg)
    lot_regions = build_lot_region_index(rows, cfg)
    item_tiers = build_item_tier_index(
        rows,
        cfg,
        type_index,
        pool,
        lot_tiers,
        is_randomizable_lot_fn=is_randomizable_lot,
        iter_slots_fn=iter_slots,
    )
    item_regions = build_item_region_index(
        rows,
        cfg,
        type_index,
        pool,
        lot_regions,
        lot_tiers,
        is_randomizable_lot_fn=is_randomizable_lot,
        iter_slots_fn=iter_slots,
    )
    return lot_regions, item_regions, lot_tiers, item_tiers

def build_tier_context(
    rows: list[dict[str, str]],
    cfg: dict,
    type_index: dict[int, int],
    pool: set[int],
) -> tuple[dict[int, int], dict[int, int]]:
    """Backward-compatible: lot/item tier maps only."""
    _lot_regions, _item_regions, lot_tiers, item_tiers = build_region_context(
        rows, cfg, type_index, pool
    )
    return lot_tiers, item_tiers

def build_region_panel_cache(
    rows: list[dict[str, str]],
    cfg: dict,
    type_index: dict[int, int],
    pool: set[int],
) -> RegionPanelCache:
    from collections import defaultdict

    from region_tiers import region_display_label

    lot_regions, item_regions, lot_tiers, item_tiers = build_region_context(
        rows, cfg, type_index, pool
    )
    dlc_rules = cfg.get("dlc_rules") or load_dlc_rules()
    slot_counts: Counter = Counter()
    tier_buckets: dict[str, list[int]] = defaultdict(list)

    if should_use_pickup_slot_index(cfg):
        from pickup_slot_index import DEFAULT_PICKUP_INDEX_PATH, load_pickup_slot_index

        index = load_pickup_slot_index(
            Path(cfg.get("pickup_slot_index_path", DEFAULT_PICKUP_INDEX_PATH))
        )
        placements = (index or {}).get("placements") or []
        rows_by_lot = _rows_by_lot_id(rows)
        lot_to_region = _lot_to_region_from_pickup_index(
            placements, rows_by_lot, cfg, lot_regions
        )
        for lot_id in sorted(lot_to_region):
            row = rows_by_lot.get(lot_id)
            if not row:
                continue
            if not lot_in_randomize_pool(row, lot_id, cfg, type_index, dlc_rules):
                continue
            region_key = lot_to_region[lot_id]
            for _ in lot_randomizable_slots(row, cfg, type_index):
                slot_counts[region_key] += 1
                tier_buckets[region_key].append(lot_tiers.get(lot_id, 5))
    else:
        for row in rows:
            lot_id = parse_int(row.get("ID"))
            if not lot_in_randomize_pool(row, lot_id, cfg, type_index, dlc_rules):
                continue
            region_key = lot_regions.get(lot_id, "T5")
            for _ in lot_randomizable_slots(row, cfg, type_index):
                slot_counts[region_key] += 1
                tier_buckets[region_key].append(lot_tiers.get(lot_id, 5))

    local_pool: Counter = Counter()
    for item_id in pool:
        local_pool[item_regions.get(item_id, "T5")] += 1

    region_lot_tier = {
        region: int(round(sum(tiers) / len(tiers)))
        for region, tiers in tier_buckets.items()
        if tiers
    }
    rows_data: list[tuple[str, int, int]] = []
    for key in slot_counts:
        rows_data.append((key, slot_counts.get(key, 0), local_pool.get(key, 0)))
    rows_data.sort(key=lambda row: (-row[1], region_display_label(row[0])))

    _ = region_display_label
    return RegionPanelCache(
        rows_data=rows_data,
        pool_size=len(pool),
        region_lot_tier=region_lot_tier,
        pool=pool,
        item_regions=item_regions,
        item_tiers=item_tiers,
    )

def compute_effective_pools(cache: RegionPanelCache, cfg: dict) -> dict[str, int]:
    from region_tiers import effective_pool_size

    effective_pool: dict[str, int] = {}
    for region_key, _n_slots, _n_local in cache.rows_data:
        lot_tier = cache.region_lot_tier.get(region_key, 5)
        effective_pool[region_key] = effective_pool_size(
            region_key,
            lot_tier,
            cache.pool,
            cache.item_regions,
            cache.item_tiers,
            cfg,
        )
    return effective_pool

def build_region_panel_data(
    rows: list[dict[str, str]],
    cfg: dict,
    type_index: dict[int, int],
    pool: set[int],
) -> tuple[dict[str, int], dict[str, int], dict[str, int], int]:
    """Per-region: pickup slots, local pool size, effective pool at current strictness."""
    cache = build_region_panel_cache(rows, cfg, type_index, pool)
    effective_pool = compute_effective_pools(cache, cfg)
    slot_counts = {key: slots for key, slots, _local in cache.rows_data}
    local_pool = {key: local for key, _slots, local in cache.rows_data}
    return (
        slot_counts,
        local_pool,
        effective_pool,
        len(cache.rows_data),
    )

def _region_weighted_choice(
    rng: random.Random,
    candidates: list[int],
    lot_region: str,
    lot_tier: int,
    item_regions: dict[int, str],
    item_tiers: dict[int, int],
    cfg: dict,
) -> int | None:
    if not candidates:
        return None
    from region_tiers import pool_match_weight, region_strictness

    if region_strictness(cfg) >= 1.0:
        return rng.choice(candidates)

    weighted: list[int] = []
    weights: list[float] = []
    for item_id in candidates:
        weight = pool_match_weight(
            lot_region,
            item_regions.get(item_id, "T5"),
            lot_tier,
            item_tiers.get(item_id, 5),
            cfg,
        )
        if weight > 0:
            weighted.append(item_id)
            weights.append(weight)
    if not weighted:
        return None
    return rng.choices(weighted, weights=weights, k=1)[0]

def _pick_tier_target(
    rng: random.Random,
    pool: set[int],
    type_index: dict[int, int],
    cfg: dict,
    lot_region: str,
    lot_tier: int,
    item_regions: dict[int, str],
    item_tiers: dict[int, int],
    *,
    used_uniques: set[int] | None = None,
    skip_src: int | None = None,
) -> int | None:
    """Pick one item for a lot slot; region_strictness controls cross-region mixing."""
    from goods_subcats import is_unique_pool_item

    used_uniques = used_uniques or set()
    candidates: list[int] = []
    for item_id in pool:
        if skip_src is not None and item_id == skip_src:
            continue
        if is_unique_pool_item(item_id, type_index, cfg) and item_id in used_uniques:
            continue
        candidates.append(item_id)
    return _region_weighted_choice(
        rng, candidates, lot_region, lot_tier, item_regions, item_tiers, cfg
    )

def _pick_from_multiset(
    rng: random.Random,
    remaining: list[int],
    type_index: dict[int, int],
    cfg: dict,
    lot_region: str,
    lot_tier: int,
    item_regions: dict[int, str],
    item_tiers: dict[int, int],
    used_uniques: set[int],
    required_true_cat: int | None = None,
    exclude_item_ids: set[int] | None = None,
) -> int | None:
    """Pick one item from the regional multiset bag — uniform among valid candidates."""
    from goods_subcats import is_unique_pool_item

    exclude = exclude_item_ids or set()
    candidates: list[int] = []
    for item_id in remaining:
        if item_id in exclude:
            continue
        if not is_valid_shuffle_target(item_id, type_index, cfg):
            continue
        if required_true_cat is not None:
            item_cat = type_index.get(item_id)
            if item_cat is None or item_cat != required_true_cat:
                continue
        if is_unique_pool_item(item_id, type_index, cfg) and item_id in used_uniques:
            continue
        candidates.append(item_id)
    if not candidates:
        return None
    return rng.choice(candidates)


def _fallback_other_than_src(
    rng: random.Random,
    pool: set[int],
    src: int,
    type_index: dict[int, int],
    cfg: dict,
) -> int | None:
    """Last resort: any legal pool item that is not the slot's original id."""
    cands = [
        item_id
        for item_id in pool
        if item_id != src and is_valid_shuffle_target(item_id, type_index, cfg)
    ]
    if not cands:
        return None
    return rng.choice(cands)


def _accept_slot_target(
    tgt: int | None,
    src: int,
    remaining: list[int],
    type_index: dict[int, int],
    cfg: dict,
    used_uniques: set[int],
    slot_targets: dict[tuple[int, int], int],
    lot_id: int,
    slot_idx: int,
) -> bool:
    """Write a non-original target. False when nothing legal exists."""
    from goods_subcats import is_unique_pool_item

    exclude = cfg.get("exclude_item_ids", set())
    if tgt is None or tgt == src or tgt in exclude:
        return False
    if not is_valid_shuffle_target(tgt, type_index, cfg):
        return False
    if tgt in remaining:
        _consume_multiset_item(remaining, tgt)
    if is_unique_pool_item(tgt, type_index, cfg):
        used_uniques.add(tgt)
    slot_targets[(lot_id, slot_idx)] = tgt
    return True


def _consume_multiset_item(remaining: list[int], item_id: int) -> None:
    try:
        remaining.remove(item_id)
    except ValueError:
        pass

def _assign_slot_targets_for_slots(
    region_slots: list[tuple[int, int, int]],
    rng: random.Random,
    type_index: dict[int, int],
    cfg: dict,
    lot_regions: dict[int, str],
    item_regions: dict[int, str],
    lot_tiers: dict[int, int],
    item_tiers: dict[int, int],
) -> dict[tuple[int, int], int]:
    """Shuffle one region's lot slots (multiset) + golden-rune sources from item pool.

    Golden-rune sources (2900–2999) do not enter the multiset bag; they draw from
    shuffle_target_pool, preferring non-rune targets.
    """
    from goods_subcats import is_golden_rune_item

    if not region_slots:
        return {}

    remaining = [
        src for _lot_id, _slot_idx, src in region_slots if not is_golden_rune_item(src)
    ]
    non_rune_order = [
        (lot_id, slot_idx, src)
        for lot_id, slot_idx, src in region_slots
        if not is_golden_rune_item(src)
    ]
    rune_order = [
        (lot_id, slot_idx, src)
        for lot_id, slot_idx, src in region_slots
        if is_golden_rune_item(src)
    ]
    rng.shuffle(non_rune_order)
    rng.shuffle(rune_order)

    used_uniques: set[int] = set()
    slot_targets: dict[tuple[int, int], int] = {}
    full_pool = set(cfg.get("shuffle_target_pool") or ())
    non_rune_pool = {i for i in full_pool if not is_golden_rune_item(i)}

    # 1) Non-rune: bag first, then pool fallback. Never leave a legal slot unwritten.
    for lot_id, slot_idx, src in non_rune_order:
        lot_region = lot_regions.get(lot_id, "T5")
        lot_tier = lot_tiers.get(lot_id, 5)
        tgt = _pick_from_multiset(
            rng,
            remaining,
            type_index,
            cfg,
            lot_region,
            lot_tier,
            item_regions,
            item_tiers,
            used_uniques,
            exclude_item_ids={src},
        )
        if not _accept_slot_target(
            tgt, src, remaining, type_index, cfg, used_uniques, slot_targets, lot_id, slot_idx
        ):
            tgt = _pick_tier_target(
                rng,
                non_rune_pool or full_pool,
                type_index,
                cfg,
                lot_region,
                lot_tier,
                item_regions,
                item_tiers,
                used_uniques=used_uniques,
                skip_src=src,
            )
            if not _accept_slot_target(
                tgt, src, remaining, type_index, cfg, used_uniques, slot_targets, lot_id, slot_idx
            ):
                tgt = _fallback_other_than_src(rng, full_pool, src, type_index, cfg)
                _accept_slot_target(
                    tgt, src, remaining, type_index, cfg, used_uniques, slot_targets, lot_id, slot_idx
                )

    # 2) Golden-rune sources: draw from category-switch pool (prefer not-in-bag leftovers)
    bag_left = set(remaining)
    preferred = {i for i in non_rune_pool if i not in bag_left}
    pool = preferred or non_rune_pool or full_pool
    for lot_id, slot_idx, src in rune_order:
        lot_region = lot_regions.get(lot_id, "T5")
        lot_tier = lot_tiers.get(lot_id, 5)
        tgt = _pick_tier_target(
            rng,
            pool,
            type_index,
            cfg,
            lot_region,
            lot_tier,
            item_regions,
            item_tiers,
            used_uniques=used_uniques,
            skip_src=src,
        )
        if not _accept_slot_target(
            tgt, src, remaining, type_index, cfg, used_uniques, slot_targets, lot_id, slot_idx
        ):
            tgt = _fallback_other_than_src(rng, full_pool or pool, src, type_index, cfg)
            _accept_slot_target(
                tgt, src, remaining, type_index, cfg, used_uniques, slot_targets, lot_id, slot_idx
            )

    return slot_targets


def _absorb_slot_sources_into_pool(
    rows: list[dict[str, str]],
    cfg: dict,
    type_index: dict[int, int],
) -> None:
    """Randomizable slot sources join the drawable pool (hard excludes stay out)."""
    from goods_subcats import is_gathering_material_id, is_goods_hard_excluded

    pool = set(cfg.get("shuffle_target_pool") or ())
    all_ids = cfg.get("category_switch_all_ids")
    for _lot, _slot, src in collect_randomizable_slots(rows, cfg, type_index):
        if src <= 0 or is_goods_hard_excluded(src):
            continue
        if is_gathering_material_id(src):
            continue
        pool.add(src)
        if isinstance(all_ids, set):
            all_ids.add(src)
    cfg["shuffle_target_pool"] = pool


def build_slot_shuffle_plan(
    rows: list[dict[str, str]],
    seed: int,
    cfg: dict,
    type_index: dict[int, int],
) -> ShufflePlan:
    """Shuffle participating lot items per map region (multiset) + GUI + NT filter."""
    _absorb_slot_sources_into_pool(rows, cfg, type_index)
    all_slots = collect_randomizable_slots(rows, cfg, type_index)
    if not all_slots:
        return ShufflePlan({}, {}, [], SHUFFLE_MODE_SLOT, 0)

    item_pool = {src for _lot_id, _slot_idx, src in all_slots}
    lot_regions, item_regions, lot_tiers, item_tiers = build_region_context(
        rows, cfg, type_index, item_pool
    )

    rng = random.Random(seed)
    by_region: dict[str, list[tuple[int, int, int]]] = {}
    if should_use_pickup_slot_index(cfg):
        from pickup_slot_index import DEFAULT_PICKUP_INDEX_PATH, load_pickup_slot_index

        index = load_pickup_slot_index(
            Path(cfg.get("pickup_slot_index_path", DEFAULT_PICKUP_INDEX_PATH))
        )
        rows_by_lot = _rows_by_lot_id(rows)
        placements = (index or {}).get("placements") or []
        lot_to_region = _lot_to_region_from_pickup_index(
            placements, rows_by_lot, cfg, lot_regions
        )
        for lot_id, slot_idx, src in all_slots:
            region = lot_to_region.get(lot_id, lot_regions.get(lot_id, "T5"))
            by_region.setdefault(region, []).append((lot_id, slot_idx, src))
    else:
        for slot in all_slots:
            region = lot_regions.get(slot[0], "T5")
            by_region.setdefault(region, []).append(slot)

    slot_targets: dict[tuple[int, int], int] = {}
    for region in sorted(by_region):
        slot_targets.update(
            _assign_slot_targets_for_slots(
                by_region[region],
                rng,
                type_index,
                cfg,
                lot_regions,
                item_regions,
                lot_tiers,
                item_tiers,
            )
        )

    return ShufflePlan(
        {},
        slot_targets,
        [],
        SHUFFLE_MODE_SLOT,
        len(all_slots),
    )

def build_shuffle_plan(
    rows: list[dict[str, str]],
    sources: set[int],
    pool: set[int],
    seed: int,
    cfg: dict,
    type_index: dict[int, int],
) -> ShufflePlan:
    return build_slot_shuffle_plan(rows, seed, cfg, type_index)

