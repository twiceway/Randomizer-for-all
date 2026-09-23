#!/usr/bin/env python3
"""Build enemy_map_regions.json + refresh enemy_map_progression tier column (T-093)."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import SCRIPT_DIR  # frozen-safe
sys.path.insert(0, str(SCRIPT_DIR))

from enemy_world_progression import load_world_regions, resolve_region_tier  # noqa: E402
from paths import OUTPUT_REPORTS  # noqa: E402

DEFAULT_INDEX = SCRIPT_DIR / "cache" / "enemy_index.json"
CATEGORIES_JSON = SCRIPT_DIR / "enemy_categories.json"
OUT_JSON = SCRIPT_DIR / "enemy_map_regions.json"
OUT_PROGRESSION = SCRIPT_DIR / "enemy_map_progression.json"

# Coarse overworld block sizes that share the same tile index space as `_00`.
_COARSE_TILE_BLOCKS = frozenset({"00", "10"})

_GROUND_MAP_IN_NAME_RE = re.compile(
    r"^(m60_\d{2}_\d{2}_\d{2})(?:-|$)", re.IGNORECASE
)

DUNGEON_MAP_REGIONS: dict[str, str] = {
    "m10_00_00_00": "limgrave",  # 史东薇尔城
    "m10_01_00_00": "limgrave",
    "m11_05_00_00": "limgrave",
    "m11_10_00_00": "limgrave",
    "m12_01_00_00": "leyndell",
    "m12_02_00_00": "leyndell",
    "m12_03_00_00": "ashen",
    "m12_04_00_00": "leyndell",
    "m12_05_00_00": "ashen",
    "m12_07_00_00": "leyndell",
    "m12_08_00_00": "leyndell",
    "m12_09_00_00": "leyndell",
    "m14_00_00_00": "liurnia",
    "m15_00_00_00": "haligtree",
    "m16_00_00_00": "weeping",
    "m19_00_00_00": "limgrave",
    "m25_00_00_00": "limgrave",
    "m30_00_00_00": "liurnia",
    "m30_10_00_00": "limgrave",
    "m30_11_00_00": "weeping",
    "m30_17_00_00": "mountaintops",
    "m30_18_00_00": "mountaintops",
    "m30_21_00_00": "consecrated",
    "m31_15_00_00": "catacombs_omen",
    "m31_81_00_00": "dlc_gravesite",
    "m31_82_00_00": "dlc_gravesite",
    "m32_00_00_00": "siofra",
    "m32_01_00_00": "siofra",
    "m32_02_00_00": "ainsel",
    "m32_04_00_00": "deeperroot",
    "m32_07_00_00": "mohgwyn",
    "m32_08_00_00": "lakeofrot",
    "m35_00_00_00": "gelmir",
    "m39_20_00_00": "farum",
}

PREFIX_REGION: dict[str, str] = {
    "m30_": "liurnia",
    "m31_": "liurnia",
    "m32_": "siofra",
    "m34_": "farum",
    "m10_": "limgrave",
    "m11_": "limgrave",
    "m12_": "leyndell",
    "m14_": "liurnia",
    "m15_": "haligtree",
    "m16_": "weeping",
    "m19_": "limgrave",
    "m25_": "limgrave",
    "m35_": "gelmir",
    "m39_": "farum",
}


def overworld_tile_region(x: int, y: int) -> tuple[str, str]:
    """Approximate ER open-world tile → T-093 region (coord fallback; coarse `_00`/`_10` only)."""
    # 南：啜泣 / 宁姆南缘
    if y >= 54:
        return ("weeping", "coord:peninsula") if x <= 34 else ("limgrave", "coord:south")
    if y >= 48:
        return ("weeping", "coord:peninsula_mid") if x <= 36 else ("limgrave", "coord:south_mid")
    # 北：化圣 / 山顶
    if y <= 16:
        return "consecrated", "coord:north"
    if y <= 20 and x >= 44:
        return "mountaintops", "coord:mountain"
    # 东：盖利德 / 龙墓
    if x >= 50 and 34 <= y <= 54:
        return "caelid", "coord:caelid"
    if x >= 48 and y <= 34:
        return "dragonbarrow", "coord:dragonbarrow"
    # 西：利耶尼亚
    if x <= 34 and 34 <= y <= 52:
        return "liurnia", "coord:liurnia"
    # 中北：禁域 / 亚坛（勿吞宁姆）
    if y <= 24 and 38 <= x <= 52:
        return "forbidden", "coord:capital_outer"
    if y <= 30 and 34 <= x <= 50:
        return "altus", "coord:altus"
    # 格密尔：窄带西北，禁止覆盖门前（x≈42,y≈36）
    if 34 <= x <= 40 and 28 <= y <= 33:
        return "gelmir", "coord:gelmir"
    # 腐败湖口袋
    if 36 <= x <= 44 and 20 <= y <= 27:
        return "lakeofrot", "coord:rot"
    # 宁姆心腹（门前 / 风暴丘）
    if 35 <= x <= 47 and 33 <= y <= 47:
        return "limgrave", "coord:limgrave"
    return "limgrave", "coord:default"


def _parse_m60(map_id: str) -> tuple[int, int, str] | None:
    parts = map_id.split("_")
    if len(parts) < 4 or parts[0] != "m60":
        return None
    try:
        return int(parts[1], 10), int(parts[2], 10), parts[3]
    except ValueError:
        return None


def _is_coarse_m60_block(block: str) -> bool:
    return block in _COARSE_TILE_BLOCKS


def load_explicit_fine_map_overrides(
    categories_path: Path = CATEGORIES_JSON,
) -> dict[str, tuple[str, str]]:
    """event_map → (region_id | parent_map_id, reason). region via parent resolved later."""
    out: dict[str, tuple[str, str]] = {}
    if not categories_path.is_file():
        return out
    cats = json.loads(categories_path.read_text(encoding="utf-8-sig"))
    for mid in cats.get("cnv_caravan_event_maps") or []:
        mid_s = str(mid)
        out[mid_s] = ("limgrave", "override:caravan_event")
    # mausoleum: inherit from ground map embedded in slot id
    for entry in cats.get("cnv_mausoleum_slots") or []:
        if not isinstance(entry, dict):
            continue
        event_map = str(entry.get("event_map") or "")
        slot = str(entry.get("slot") or "")
        if not event_map or not slot:
            continue
        m = _GROUND_MAP_IN_NAME_RE.match(slot)
        if not m:
            continue
        parent = m.group(1)
        # Prefer first entry; later entries on same event_map keep first unless empty
        out.setdefault(event_map, (parent, f"override:mausoleum_parent:{parent}"))
    return out


def infer_parent_map_from_slot_names(slot_names: list[str]) -> str | None:
    """Majority ground `m60_*_*_*` prefix from event-layer entity names."""
    counts: Counter[str] = Counter()
    for name in slot_names:
        m = _GROUND_MAP_IN_NAME_RE.match(str(name or ""))
        if m:
            counts[m.group(1)] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def resolve_map_region_coarse(map_id: str) -> tuple[str, str]:
    """Dungeon / DLC / coarse overworld only — never fine-grid coord heuristic."""
    if map_id in DUNGEON_MAP_REGIONS:
        return DUNGEON_MAP_REGIONS[map_id], "field"
    parts = map_id.split("_")
    if len(parts) >= 4 and parts[0] == "m61":
        try:
            x = int(parts[1], 10)
        except ValueError:
            return "dlc_gravesite", "dlc:parse_fail"
        if x >= 46:
            return "dlc_abyss", "dlc:abyss"
        if x >= 44:
            return "dlc_rauh", "dlc:rauh"
        if x >= 42:
            return "dlc_south", "dlc:south"
        if x >= 40:
            return "dlc_altus", "dlc:altus"
        return "dlc_gravesite", "dlc:gravesite"
    parsed = _parse_m60(map_id)
    if parsed is not None:
        x, y, block = parsed
        if _is_coarse_m60_block(block):
            return overworld_tile_region(x, y)
        # Fine grid must not reach here for final answer without parent.
        return "limgrave", "fine_needs_parent"
    for prefix, region in PREFIX_REGION.items():
        if map_id.startswith(prefix):
            return region, f"prefix:{prefix}"
    if parts[0] != "m60":
        return "liurnia", "dungeon_default"
    return "limgrave", "default"


def resolve_map_region(map_id: str) -> tuple[str, str]:
    """Backward-compatible single-map resolve (no index). Fine maps → limgrave fallback."""
    parsed = _parse_m60(map_id)
    if parsed is not None and not _is_coarse_m60_block(parsed[2]):
        overrides = load_explicit_fine_map_overrides()
        if map_id in overrides:
            target, reason = overrides[map_id]
            if target in (
                "limgrave",
                "weeping",
                "liurnia",
                "caelid",
                "consecrated",
                "altus",
                "gelmir",
                "dragonbarrow",
                "forbidden",
                "mountaintops",
                "lakeofrot",
            ) or not target.startswith("m60_"):
                return target, reason
            region, parent_reason = resolve_map_region_coarse(target)
            return region, f"{reason}|{parent_reason}"
        return "limgrave", "fine_fallback_limgrave"
    return resolve_map_region_coarse(map_id)


def _slot_names_by_map(index: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for slot in index.get("slots") or []:
        mid = str(slot.get("map_id") or "")
        if not mid:
            continue
        out.setdefault(mid, []).append(str(slot.get("name") or ""))
    return out


def build(index_path: Path = DEFAULT_INDEX) -> dict:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    map_ids = sorted({str(s.get("map_id", "")) for s in index.get("slots", []) if s.get("map_id")})
    world = load_world_regions()
    names_by_map = _slot_names_by_map(index)
    overrides = load_explicit_fine_map_overrides()

    by_map_id: dict[str, dict] = {}
    tier_by_map: dict[str, int] = {}
    region_hist: Counter[str] = Counter()
    # Cache resolved regions for parent lookups
    resolved: dict[str, tuple[str, str]] = {}

    def resolve_one(mid: str, stack: set[str] | None = None) -> tuple[str, str]:
        if mid in resolved:
            return resolved[mid]
        stack = stack or set()
        if mid in stack:
            return "limgrave", "inherit:cycle_fallback"
        stack.add(mid)

        parsed = _parse_m60(mid)
        if parsed is None or _is_coarse_m60_block(parsed[2]):
            region_id, reason = resolve_map_region_coarse(mid)
            resolved[mid] = (region_id, reason)
            return region_id, reason

        # Fine / event layer
        if mid in overrides:
            target, reason = overrides[mid]
            if target.startswith("m60_"):
                parent_region, parent_reason = resolve_one(target, stack)
                resolved[mid] = (parent_region, f"{reason}|{parent_reason}")
                return resolved[mid]
            resolved[mid] = (target, reason)
            return resolved[mid]

        parent = infer_parent_map_from_slot_names(names_by_map.get(mid) or [])
        if parent and parent != mid:
            parent_region, parent_reason = resolve_one(parent, stack)
            # If parent is also fine (_10 night of ground), still OK
            resolved[mid] = (
                parent_region,
                f"inherit:slot_parent:{parent}|{parent_reason}",
            )
            return resolved[mid]

        resolved[mid] = ("limgrave", "fine_fallback_limgrave")
        return resolved[mid]

    for mid in map_ids:
        region_id, reason = resolve_one(mid)
        # Safety: fine maps must never keep raw coord:north
        parsed = _parse_m60(mid)
        if (
            parsed is not None
            and not _is_coarse_m60_block(parsed[2])
            and reason.startswith("coord:")
        ):
            region_id, reason = "limgrave", "fine_blocked_coord_heuristic"
        tier = resolve_region_tier(region_id, world=world)
        by_map_id[mid] = {"region_id": region_id, "tier": tier, "reason": reason}
        tier_by_map[mid] = tier
        region_hist[region_id] += 1

    return {
        "schema": "enemy_map_regions_v1",
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_index": str(index_path.name),
        "map_count": len(by_map_id),
        "default_region": "limgrave",
        "by_map_id": by_map_id,
        "_region_histogram": dict(sorted(region_hist.items())),
        "_tier_by_map": tier_by_map,
    }


def write_progression(payload: dict) -> None:
    OUT_PROGRESSION.write_text(
        json.dumps(
            {
                "schema": "enemy_map_progression_t093",
                "built_at": payload.get("built_at"),
                "source": "enemy_map_regions.json",
                "default_tier": 1,
                "dungeon_default_tier": 3,
                "dlc_default_tier": 21,
                "dlc_map_prefix": "m61_",
                "by_map_id": payload.get("_tier_by_map") or {},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_fine_map_audit(payload: dict, previous: dict[str, Any] | None = None) -> Path:
    report = OUTPUT_REPORTS / "地图大区归属审计.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    by_new = payload.get("by_map_id") or {}
    by_old = (previous or {}).get("by_map_id") or {}
    lines = [
        "# 地图大区归属审计",
        "",
        f"built_at: {payload.get('built_at')}",
        f"maps: {payload.get('map_count')}",
        "",
        "## 非 `_00` 细网格 / 事件层",
        "",
        "| map | 旧 region/tier | 新 region/tier | reason |",
        "|-----|----------------|----------------|--------|",
    ]
    fine_coord_north = 0
    for mid in sorted(by_new):
        parsed = _parse_m60(mid)
        if parsed is None:
            continue
        if parsed[2] == "00":
            continue
        neu = by_new[mid]
        old = by_old.get(mid) or {}
        if str(neu.get("reason", "")).startswith("coord:north") or (
            not _is_coarse_m60_block(parsed[2]) and neu.get("reason") == "coord:north"
        ):
            fine_coord_north += 1
        lines.append(
            f"| `{mid}` | {old.get('region_id', '-')}/{old.get('tier', '-')} | "
            f"{neu.get('region_id')}/{neu.get('tier')} | {neu.get('reason')} |"
        )
    lines.extend(
        [
            "",
            f"**细网格 `coord:north` 计数**: {fine_coord_north}（目标 0）",
            "",
        ]
    )
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    previous = None
    if OUT_JSON.is_file():
        previous = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    payload = build()
    public = {k: v for k, v in payload.items() if not k.startswith("_")}
    OUT_JSON.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_progression(payload)
    report = OUTPUT_REPORTS / "T-093_地图大区归属表.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# T-093 地图大区归属表", "", f"maps: {payload['map_count']}", ""]
    for mid in sorted(public.get("by_map_id", {})):
        e = public["by_map_id"][mid]
        lines.append(f"| {e['tier']} | {e['region_id']} | `{mid}` | {e['reason']} |")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    audit = write_fine_map_audit(public, previous)
    # count fine coord:north
    n_bad = 0
    for mid, e in (public.get("by_map_id") or {}).items():
        parsed = _parse_m60(mid)
        if parsed and not _is_coarse_m60_block(parsed[2]) and str(e.get("reason", "")).startswith(
            "coord:"
        ):
            n_bad += 1
    print(f"wrote {OUT_JSON.name} maps={payload['map_count']} fine_coord_reasons={n_bad}")
    print(f"audit {audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
