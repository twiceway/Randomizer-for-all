#!/usr/bin/env python3
"""Map lot / item progression tiers for regional weighted shuffle."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
RULES_PATH = SCRIPT_DIR / "region_tiers.json"
DLC_RULES_PATH = SCRIPT_DIR / "dlc_item_rules.json"

_BRACKET_RE = re.compile(r"\[([^\]]+)\]")
_BOSS_NAME_HINTS = (
    "remembrance",
    "great rune",
    "boss drop",
    "divine tower",
)


@lru_cache(maxsize=1)
def load_dlc_region_rules(path: Path | None = None) -> dict:
    path = path or DLC_RULES_PATH
    if not path.exists():
        return {"item_ranges": [], "lot_ranges": [], "region_keywords": []}
    data = json.loads(path.read_text(encoding="utf-8"))

    def _ranges(key: str) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for entry in data.get(key, []):
            if len(entry) != 2:
                continue
            lo, hi = int(entry[0]), int(entry[1])
            if lo <= hi:
                out.append((lo, hi))
        return out

    return {
        "item_ranges": _ranges("id_ranges"),
        "lot_ranges": _ranges("lot_id_ranges"),
        "region_keywords": [
            str(k).strip() for k in data.get("region_keywords", []) if str(k).strip()
        ],
    }


def dlc_region_key(rules: dict | None = None) -> str:
    rules = rules or load_region_rules()
    return str(rules.get("dlc_region", "DLC"))


def dlc_progress_tier(rules: dict | None = None) -> int:
    rules = rules or load_region_rules()
    tier_max = int(rules.get("tier_count", 10))
    return max(1, min(tier_max, int(rules.get("dlc_tier", 9))))


def _dlc_name_excluded(name: str) -> bool:
    """Base-game areas that share DLC keyword substrings."""
    low = name.lower()
    if "haligtree" in low and "elphael" in low:
        return True
    if "miquella's haligtree" in low:
        return True
    return False


def _dlc_keyword_hit(name: str, keywords: list[str]) -> bool:
    if _dlc_name_excluded(name):
        return False
    low = name.lower()
    return any(keyword.lower() in low for keyword in keywords)


def is_dlc_item_id(item_id: int, dlc_rules: dict | None = None) -> bool:
    dlc_rules = dlc_rules or load_dlc_region_rules()
    return any(lo <= item_id <= hi for lo, hi in dlc_rules.get("item_ranges", []))


def is_dlc_map_lot(
    row: dict[str, str], lot_id: int, dlc_rules: dict | None = None
) -> bool:
    """Geographic DLC map bucket — lot id / place name only (not broad item-id heuristics)."""
    dlc_rules = dlc_rules or load_dlc_region_rules()
    for lo, hi in dlc_rules.get("lot_ranges", []):
        if lo <= lot_id <= hi:
            return True
    name = row.get("Name") or ""
    return _dlc_keyword_hit(name, dlc_rules.get("region_keywords", []))


@lru_cache(maxsize=1)
def load_region_rules(path: Path | None = None) -> dict:
    path = path or RULES_PATH
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _match_keywords(text: str, rules: list[dict]) -> int | None:
    low = text.lower()
    for entry in rules:
        for pattern in entry.get("patterns", []):
            if pattern.lower() in low:
                return int(entry["tier"])
    return None


def parse_lot_label(name: str) -> tuple[str, str]:
    """Return (region_token, subarea_token) from lot Name (leading [..] only)."""
    name = name or ""
    if not name.startswith("["):
        return "", ""
    m = _BRACKET_RE.search(name)
    if not m or m.start() != 0:
        return "", ""
    head = m.group(1).strip()
    if " - " in head:
        region, sub = head.split(" - ", 1)
        return region.strip(), sub.strip()
    return head, ""


def is_boss_lot_row(row: dict[str, str], lot_id: int, rules: dict) -> bool:
    for lo, hi in rules.get("boss_lot_id_ranges", []):
        if int(lo) <= lot_id <= int(hi):
            return True
    name = (row.get("Name") or "").lower()
    return any(hint in name for hint in _BOSS_NAME_HINTS)


def lot_tier_from_id(lot_id: int, rules: dict) -> int | None:
    for entry in rules.get("lot_id_ranges", []):
        lo, hi = int(entry["min"]), int(entry["max"])
        if lo <= lot_id <= hi:
            return int(entry["tier"])
    if 10_000_000 <= lot_id < 20_000_000:
        lead = lot_id // 1_000_000
        if lead <= 12:
            return 5
        if lead <= 14:
            return 6
        if lead <= 16:
            return 7
        if lead <= 18:
            return 8
        return 9
    if 30_000_000 <= lot_id < 40_000_000:
        lead = lot_id // 1_000_000
        if lead <= 31:
            return 4
        if lead <= 33:
            return 5
        return 6
    if 100_000_000 <= lot_id < 300_000_000:
        return 5
    if 300_000_000 <= lot_id < 600_000_000:
        return 6
    if lot_id >= 1_000_000_000:
        return 5
    return None


def lot_tier(row: dict[str, str], lot_id: int, rules: dict | None = None) -> int:
    rules = rules or load_region_rules()
    tier_max = int(rules.get("tier_count", 10))
    default_tier = int(rules.get("default_tier", 5))

    if is_dlc_map_lot(row, lot_id):
        return dlc_progress_tier(rules)

    if is_boss_lot_row(row, lot_id, rules):
        return tier_max

    id_tier = lot_tier_from_id(lot_id, rules)
    if id_tier is not None:
        return max(1, min(tier_max, id_tier))

    region, sub = parse_lot_label(row.get("Name") or "")
    keyword_rules = rules.get("region_keywords", [])
    dungeon_rules = rules.get("dungeon_keywords", [])

    if region.upper() == "LD" and sub:
        hit = _match_keywords(sub, dungeon_rules)
        if hit is not None:
            return max(1, min(tier_max, hit))
        hit = _match_keywords(sub, keyword_rules)
        if hit is not None:
            return max(1, min(tier_max, hit))

    for token in (sub, region, f"{region} {sub}".strip()):
        if not token:
            continue
        hit = _match_keywords(token, keyword_rules)
        if hit is not None:
            return max(1, min(tier_max, hit))

    return default_tier


def intrinsic_item_tier(item_id: int, cat: int | None, subcat: str | None, rules: dict) -> int | None:
    tier_max = int(rules.get("tier_count", 10))
    if subcat in {"remembrance", "great_rune"}:
        return tier_max
    if subcat == "spirit_greater":
        return tier_max - 1
    if subcat in {"golden_seed", "sacred_tear", "larval_tear", "memory_stone"}:
        return 3
    if subcat in {"stone_somber", "stone_special"}:
        return 6
    if subcat in {"stone_smithing", "spirit_upgrade"}:
        return 4
    if subcat == "rune":
        # CNV map rune placeholders 2900+ are low-tier pickups
        if 2900 <= item_id <= 2999:
            return max(1, int(rules.get("rune_placeholder_tier", 2)))
        return 3
    if subcat == "spell_rune":
        return 5
    if cat == 0:  # weapon — rough band from id magnitude
        if item_id >= 30_000_000:
            return 8
        if item_id >= 10_000_000:
            return 6
        if item_id >= 1_000_000:
            return 4
        return 2
    if cat == 2:  # armor
        if item_id >= 5_000_000:
            return 7
        if item_id >= 1_000_000:
            return 5
        return 3
    if cat in {3, 4}:  # talisman, ash
        if item_id >= 1_000_000:
            return 6
        return 4
    return None


def region_strictness(cfg: dict) -> float:
    """0 = 仅同级区域池；1 = 全局混合（忽略等级差）。"""
    value = float(cfg.get("region_strictness", 1.0))
    return max(0.0, min(1.0, value))


def _tier_to_region_map(rules: dict) -> dict[int, str]:
    raw = rules.get("tier_to_region", {})
    out: dict[int, str] = {}
    for key, value in raw.items():
        if key == "dungeon":
            continue
        try:
            out[int(key)] = str(value)
        except ValueError:
            continue
    return out


def _match_keyword_tier(text: str, rules: dict) -> int | None:
    """Best keyword tier match on free text (longest pattern wins)."""
    low = text.lower()
    best_tier: int | None = None
    best_len = 0
    for key in ("region_keywords", "dungeon_keywords"):
        for entry in rules.get(key, []):
            tier = int(entry["tier"])
            for pattern in entry.get("patterns", []):
                pat = pattern.lower()
                if pat in low and len(pat) > best_len:
                    best_len = len(pat)
                    best_tier = tier
    return best_tier


def canonical_map_region(
    row: dict[str, str], lot_id: int, rules: dict | None = None
) -> str:
    """One pool per overworld map (Limgrave, Liurnia, …), not per cave/NPC."""
    rules = rules or load_region_rules()
    if is_dlc_map_lot(row, lot_id):
        return dlc_region_key(rules)

    tier_map = _tier_to_region_map(rules)
    default_tier = int(rules.get("default_tier", 5))
    dungeon_key = str(rules.get("tier_to_region", {}).get("dungeon", "Dungeons"))

    region, sub = parse_lot_label(row.get("Name") or "")
    name = row.get("Name") or ""
    if region.upper() == "LD":
        return dungeon_key

    canon_values = set(tier_map.values()) | {
        dungeon_key,
        "Wilderness",
        "Convergence",
        dlc_region_key(rules),
    }
    if region in canon_values:
        return region

    combined = f"{name} {region} {sub}".strip()
    hit_tier = _match_keyword_tier(combined, rules)
    if hit_tier is not None and hit_tier in tier_map:
        return tier_map[hit_tier]

    if region in {"Material", "Material Node", "Corpse", "Info Item", "Sorcery"}:
        if hit_tier is not None and hit_tier in tier_map:
            return tier_map[hit_tier]
        return "Wilderness"

    if region == "Teardrop Scarab":
        if hit_tier is not None and hit_tier in tier_map:
            return tier_map[hit_tier]
        return "Wilderness"

    if 2000 <= (lot_id // 1_000_000) <= 2099:
        return "Convergence"

    lot_t = lot_tier(row, lot_id, rules)
    return tier_map.get(lot_t, tier_map.get(default_tier, "Altus Plateau"))


def lot_region_from_id(lot_id: int, rules: dict) -> str:
    """Fallback region bucket for lots without a place name."""
    if lot_id < 10_000:
        return f"id:{lot_id // 1000}"
    if 10_000 <= lot_id < 1_000_000:
        return f"id:{lot_id // 10_000}"
    lead = lot_id // 1_000_000
    if 10 <= lead < 100:
        return f"msb:{lead}"
    if 2000 <= lead <= 2099:
        return f"cnv:{lead}"
    if 1000 <= lead <= 1999:
        return f"map:{lead}"
    return f"id:{lead}"


def lot_region_key(row: dict[str, str], lot_id: int, rules: dict | None = None) -> str:
    """Stable region pool id — one entry per overworld map."""
    rules = rules or load_region_rules()
    return canonical_map_region(row, lot_id, rules)


def region_display_label(region_key: str) -> str:
    """Short label for GUI."""
    rules = load_region_rules()
    labels = rules.get("region_labels", {})
    if region_key in labels:
        return str(labels[region_key])
    if region_key.startswith("T"):
        return f"档位·{region_key[1:]}"
    return region_key


def pool_match_weight(
    lot_region: str,
    item_region: str,
    lot_tier: int,
    item_tier: int,
    cfg: dict,
) -> float:
    """Cross-region pick weight from region_strictness (0=本区 only, 1=全局)."""
    if lot_region == item_region:
        return 1.0
    strictness = region_strictness(cfg)
    if strictness >= 1.0:
        return 1.0
    if strictness <= 0.0:
        return 0.0
    diff = abs(int(lot_tier) - int(item_tier))
    if diff == 0:
        return strictness
    return strictness**diff


def effective_pool_size(
    region_key: str,
    lot_tier: int,
    pool: set[int],
    item_regions: dict[int, str],
    item_tiers: dict[int, int],
    cfg: dict,
) -> int:
    """GUI metric: weight sum per item (0=本区 only … 1=全池)."""
    total = 0.0
    for item_id in pool:
        total += pool_match_weight(
            region_key,
            item_regions.get(item_id, "T5"),
            lot_tier,
            item_tiers.get(item_id, 5),
            cfg,
        )
    return int(round(total))


def tier_match_weight(item_tier: int, lot_tier: int, cfg: dict) -> float:
    """等级差越大权重越低；严格度 0 时仅同级，1 时任意等级等权。"""
    diff = abs(int(item_tier) - int(lot_tier))
    if diff == 0:
        return 1.0
    strictness = region_strictness(cfg)
    if strictness >= 1.0:
        return 1.0
    if strictness <= 0.0:
        return 0.0
    return strictness**diff


def build_lot_tier_index(
    rows: list[dict[str, str]], cfg: dict
) -> dict[int, int]:
    rules = load_region_rules()
    index: dict[int, int] = {}
    for row in rows:
        lot_id = int(float(row.get("ID", 0) or 0))
        if lot_id <= 0:
            continue
        index[lot_id] = lot_tier(row, lot_id, rules)
    return index


def build_lot_region_index(
    rows: list[dict[str, str]], cfg: dict
) -> dict[int, str]:
    rules = load_region_rules()
    index: dict[int, str] = {}
    for row in rows:
        lot_id = int(float(row.get("ID", 0) or 0))
        if lot_id <= 0:
            continue
        index[lot_id] = canonical_map_region(row, lot_id, rules)
    return index


def build_item_region_index(
    rows: list[dict[str, str]],
    cfg: dict,
    type_index: dict[int, int],
    pool: set[int],
    lot_regions: dict[int, str],
    lot_tiers: dict[int, int],
    *,
    is_randomizable_lot_fn,
    iter_slots_fn,
) -> dict[int, str]:
    rules = load_region_rules()
    default_tier = int(rules.get("default_tier", 5))
    tier_map = _tier_to_region_map(rules)
    dlc_rules = load_dlc_region_rules()
    dlc_key = dlc_region_key(rules)
    item_tiers = build_item_tier_index(
        rows,
        cfg,
        type_index,
        pool,
        lot_tiers,
        is_randomizable_lot_fn=is_randomizable_lot_fn,
        iter_slots_fn=iter_slots_fn,
    )

    observed: dict[int, str] = {}
    for row in rows:
        lot_id = int(float(row.get("ID", 0) or 0))
        if not is_randomizable_lot_fn(lot_id, cfg):
            continue
        lot_region = lot_regions.get(lot_id)
        if not lot_region:
            continue
        for _slot_idx, _id_key, _cat_key, item_id, _lot_cat in iter_slots_fn(row):
            if item_id <= 0:
                continue
            if item_id not in observed:
                observed[item_id] = lot_region

    out: dict[int, str] = {}
    for item_id in pool:
        if item_id in observed:
            out[item_id] = observed[item_id]
        elif is_dlc_item_id(item_id, dlc_rules):
            out[item_id] = dlc_key
        else:
            tier = item_tiers.get(item_id, default_tier)
            out[item_id] = tier_map.get(tier, tier_map.get(default_tier, "Altus Plateau"))
    return out


def build_item_tier_index(
    rows: list[dict[str, str]],
    cfg: dict,
    type_index: dict[int, int],
    pool: set[int],
    lot_tiers: dict[int, int],
    *,
    is_randomizable_lot_fn,
    iter_slots_fn,
) -> dict[int, int]:
    from goods_subcats import goods_subcat_for

    rules = load_region_rules()
    tier_max = int(rules.get("tier_count", 10))
    default_tier = int(rules.get("default_tier", 5))

    observed: dict[int, int] = {}
    for row in rows:
        lot_id = int(float(row.get("ID", 0) or 0))
        if not is_randomizable_lot_fn(lot_id, cfg):
            continue
        lt = lot_tiers.get(lot_id, default_tier)
        for _slot_idx, _id_key, _cat_key, item_id, lot_cat in iter_slots_fn(row):
            if item_id <= 0:
                continue
            prev = observed.get(item_id)
            if prev is None or lt < prev:
                observed[item_id] = lt

    out: dict[int, int] = {}
    for item_id in pool:
        cat = type_index.get(item_id)
        sub = goods_subcat_for(item_id, cfg) if cat == 1 else None
        intrinsic = intrinsic_item_tier(item_id, cat, sub, rules)
        geo = observed.get(item_id, default_tier)
        if intrinsic is None:
            out[item_id] = geo
        else:
            out[item_id] = max(intrinsic, geo)
        out[item_id] = max(1, min(tier_max, out[item_id]))
    return out
