#!/usr/bin/env python3
"""One-off diagnostic for important subcat drop probability."""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"V:\games\Elden Ring\Game\tools\cnv_randomizer")
sys.path.insert(0, str(ROOT))

import cnv_randomizer_core as core
from goods_subcats import (
    BELL_BEARING_RANGES,
    GOODS_GROUPS,
    GOODS_SUBCAT_LABELS,
    STACKABLE_GOODS_SUBCATS,
    classify_goods_subcat,
    goods_subcat_for,
    is_unique_pool_item,
        load_goods_rows,
    load_goods_subcat_index,
    subcat_to_goods_group,
)

IMPORTANT_SUBCATS = set(GOODS_GROUPS["important"][1])
FOCUS_SUBCATS = [
    "memory_stone",
    "spirit_lesser",
    "spirit_greater",
    "crystal_tear",
]
OTHER_IMPORTANT = sorted(IMPORTANT_SUBCATS - set(FOCUS_SUBCATS))

SPOILER_PATH = ROOT / "output" / "spoiler_257728869_2026-07-17_14.37.03.txt"
OUT_PATH = ROOT / "_diag_important.txt"
SPOILER_RE = core.SPOILER_RE


def subcat_bucket(sub: str | None) -> str:
    if sub is None:
        return "(unknown)"
    if sub in FOCUS_SUBCATS:
        return sub
    if sub in IMPORTANT_SUBCATS:
        return "other_important"
    return f"non_important:{sub}"


def main() -> None:
    cfg = core.load_config(ROOT / "config.json")
    cfg["dlc_ranges"] = core.load_dlc_item_rules()
    csv_dir = Path(cfg["csv_dir"])
    goods_rows = load_goods_rows(csv_dir)
    goods_subcat_index = load_goods_subcat_index(csv_dir)
    cfg["goods_rows"] = goods_rows
    cfg["goods_subcat_index"] = goods_subcat_index
    cfg["exclude_item_ids"] = set(cfg.get("exclude_item_ids", []))
    from goods_subcats import is_goods_hard_excluded

    for item_id in goods_rows:
        if is_goods_hard_excluded(item_id):
            cfg["exclude_item_ids"].add(item_id)

    src_path = csv_dir / f"{cfg['target_param']}.csv"
    _, rows = core.read_csv(src_path)
    type_index = core.load_item_type_index(csv_dir)
    slot_counts = core.count_source_slots_by_key(rows, cfg, type_index)
    cfg["drop_target_percentages"] = core.resolve_drop_percentages(cfg, slot_counts)
    unified_pool = core.build_unified_pool(rows, cfg, type_index)
    all_slots = core.collect_randomizable_slots(rows, cfg, type_index)

    # Pool counts by subcat (goods only) and unique flags
    pool_by_subcat: Counter[str] = Counter()
    pool_unique_by_subcat: Counter[str] = Counter()
    pool_nonunique_by_subcat: Counter[str] = Counter()
    pool_goods_ids: dict[str, list[int]] = defaultdict(list)

    for item_id in sorted(unified_pool):
        cat = type_index.get(item_id)
        if cat != core.CAT_GOODS:
            continue
        sub = goods_subcat_for(item_id, cfg) or "(none)"
        pool_by_subcat[sub] += 1
        pool_goods_ids[sub].append(item_id)
        if is_unique_pool_item(item_id, type_index, cfg):
            pool_unique_by_subcat[sub] += 1
        else:
            pool_nonunique_by_subcat[sub] += 1

    unique_pool = {p for p in unified_pool if is_unique_pool_item(p, type_index, cfg)}
    stack_pool = unified_pool - unique_pool

    # Important group aggregate in pool
    imp_in_pool = sum(
        1
        for i in unified_pool
        if type_index.get(i) == core.CAT_GOODS
        and (goods_subcat_for(i, cfg) in IMPORTANT_SUBCATS)
    )
    imp_unique = sum(
        1
        for i in unique_pool
        if type_index.get(i) == core.CAT_GOODS
        and (goods_subcat_for(i, cfg) in IMPORTANT_SUBCATS)
    )

    # Spoiler target counts
    spoiler_subcat = Counter()
    spoiler_bucket = Counter()
    spoiler_lines_parsed = 0
    spoiler_important_group = 0
    if SPOILER_PATH.exists():
        for line in SPOILER_PATH.read_text(encoding="utf-8").splitlines():
            m = SPOILER_RE.match(line.strip())
            if not m:
                continue
            spoiler_lines_parsed += 1
            tgt = int(m.group(5))
            sub = goods_subcat_for(tgt, cfg)
            if sub:
                spoiler_subcat[sub] += 1
                spoiler_bucket[subcat_bucket(sub)] += 1
                if subcat_to_goods_group(sub) == "important":
                    spoiler_important_group += 1
            else:
                cat = type_index.get(tgt)
                spoiler_subcat[f"equip_cat_{cat}"] += 1
                spoiler_bucket["non_important:equipment"] += 1

    # Sample memory_stone IDs and naming evidence
    mem_ids = pool_goods_ids.get("memory_stone", [])[:15]
    mem_samples = []
    for iid in mem_ids:
        row = goods_rows.get(iid, {})
        mem_samples.append(
            (iid, row.get("Name", ""), row.get("goodsType", ""), row.get("isOnlyOne", ""))
        )

    # Count bell bearing band vs other
    bb_in_band = sum(
        1
        for i in pool_goods_ids.get("memory_stone", [])
        if any(lo <= i <= hi for lo, hi in BELL_BEARING_RANGES)
    )

    lines: list[str] = []
    w = lines.append

    w("CNV Randomizer — important subcat / drop % diagnostic")
    w("=" * 72)
    w(f"Config: {ROOT / 'config.json'}")
    w(f"Spoiler: {SPOILER_PATH.name}")
    w("")
    w("WHY 2% important feels high for ashes / memory_stone / bell bearings")
    w("-" * 72)
    w(
        "drop_target_percentages['important']=2% applies ONLY to _pick_weighted_target "
        "when filling leftover slots after unique coverage."
    )
    w(
        "build_shuffle_plan first runs _assign_slot_unique_coverage on the entire "
        "unique_pool (is_unique_pool_item=True). Every unique item must land on "
        "at least one randomizable slot, independent of the 2% group weight."
    )
    w(
        "Spirit ashes (goodsType 7/8 → spirit_lesser/spirit_greater), bell bearings "
        "(ID 229000–229099 → memory_stone), crystal tears, seeds, etc. are NOT in "
        "STACKABLE_GOODS_SUBCATS → treated as unique → forced placements."
    )
    w(
        "So high spoiler counts for 道具/重要道具 are expected when many unique "
        "important goods exist vs total slots."
    )
    w("")
    w("NAMING: memory_stone in code")
    w("-" * 72)
    w(
        f"GUI label: {GOODS_SUBCAT_LABELS.get('memory_stone')} (bell bearings / 铃珠), "
        "NOT Elden Ring Memory Stones (记忆石 talisman slots)."
    )
    w(f"Classification: BELL_BEARING_RANGES = {list(BELL_BEARING_RANGES)}")
    w(
        "Comment in goods_subcats.py: CNV map 2900–2999 runes were mislabeled; "
        "229000 band = roundtable bell bearings."
    )
    w(f"memory_stone items in unified pool: {pool_by_subcat.get('memory_stone', 0)}")
    w(f"  of those in 229000 band: {bb_in_band}")
    if mem_samples:
        w("  sample IDs (id, Name, goodsType, isOnlyOne):")
        for row in mem_samples:
            w(f"    {row}")
    w("")
    w("KEY SIZES")
    w("-" * 72)
    w(f"unified_pool (global_pool_size): {len(unified_pool)}")
    w(f"unique_pool_size: {len(unique_pool)}")
    w(f"stackable_pool_size: {len(stack_pool)}")
    w(f"randomizable_slots (collect_randomizable_slots): {len(all_slots)}")
    w(f"mapping_sources (unique source item ids): {len(core.collect_mapping_sources(rows, cfg, type_index))}")
    w(
        f"important-group goods in pool: {imp_in_pool} "
        f"(unique: {imp_unique}, stackable: {imp_in_pool - imp_unique})"
    )
    w("")
    w("Resolved drop_target_percentages (after normalize):")
    for k, v in sorted((cfg.get("drop_target_percentages") or {}).items()):
        w(f"  {k}: {v}%")
    w("")
    w("UNIFIED POOL — focus + other important subcats (goods only)")
    w("-" * 72)
    w(f"{'subcat':<18} {'label':<12} {'pool':>6} {'unique':>7} {'stack':>7} {'is_unique':>10}")
    for sub in FOCUS_SUBCATS + OTHER_IMPORTANT:
        label = GOODS_SUBCAT_LABELS.get(sub, sub)
        n = pool_by_subcat.get(sub, 0)
        u = pool_unique_by_subcat.get(sub, 0)
        s = pool_nonunique_by_subcat.get(sub, 0)
        flag = "YES" if n and u == n else ("PARTIAL" if u else "NO")
        w(f"{sub:<18} {label:<12} {n:>6} {u:>7} {s:>7} {flag:>10}")
    w("")
    w("UNIFIED POOL — all goods subcats with count>0")
    w("-" * 72)
    for sub, n in pool_by_subcat.most_common():
        u = pool_unique_by_subcat.get(sub, 0)
        grp = subcat_to_goods_group(sub) or "-"
        w(f"  {sub}: {n} (unique {u}) group={grp}")
    w("")
    w("STACKABLE_GOODS_SUBCATS (reference):")
    w("  " + ", ".join(sorted(STACKABLE_GOODS_SUBCATS)))
    w("")
    w("SPOILER TARGET COUNTS BY SUBCAT (parsed lines with SPOILER_RE)")
    w("-" * 72)
    w(f"parsed spoiler change lines: {spoiler_lines_parsed}")
    w(f"targets in goods group 'important': {spoiler_important_group}")
    w(f"share of parsed lines: {spoiler_important_group / spoiler_lines_parsed * 100:.1f}%" if spoiler_lines_parsed else "n/a")
    w("")
    w("Focus + bucket rollup:")
    for key in FOCUS_SUBCATS + ["other_important"]:
        w(f"  {key}: {spoiler_bucket.get(key, 0)}")
    w("")
    w("All subcats (spoiler targets, goods resolvable):")
    for sub, n in spoiler_subcat.most_common():
        if sub.startswith("equip_cat_"):
            continue
        w(f"  {sub}: {n}")
    w("")
    w("Equipment-category spoiler targets (not goods_subcat_for):")
    for sub, n in spoiler_subcat.most_common():
        if sub.startswith("equip_cat_"):
            w(f"  {sub}: {n}")

    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    print(f"unified={len(unified_pool)} unique={len(unique_pool)} slots={len(all_slots)}")
    for sub in FOCUS_SUBCATS + ["other_important"]:
        print(
            f"pool {sub}: {pool_by_subcat.get(sub,0)} unique={pool_unique_by_subcat.get(sub,0)} "
            f"spoiler={spoiler_bucket.get(sub,0)}"
        )


if __name__ == "__main__":
    main()

