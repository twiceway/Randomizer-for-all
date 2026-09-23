#!/usr/bin/env python3
"""Build enemy_map_progression.json from enemy_index map_ids."""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from paths import SCRIPT_DIR  # frozen-safe
sys.path.insert(0, str(SCRIPT_DIR))

from paths import OUTPUT_REPORTS  # noqa: E402

DEFAULT_INDEX = SCRIPT_DIR / "cache" / "enemy_index.json"
OUT_JSON = SCRIPT_DIR / "enemy_map_progression.json"

# Known legacy dungeon map_id -> progression tier (1~9).
DUNGEON_MAP_TIERS: dict[str, int] = {
    "m10_00_00_00": 4,  # Stormveil
    "m10_01_00_00": 1,  # Chapel of Anticipation
    "m11_05_00_00": 2,
    "m11_10_00_00": 2,
    "m12_01_00_00": 3,
    "m12_02_00_00": 3,
    "m12_04_00_00": 3,
    "m12_07_00_00": 3,
    "m12_08_00_00": 3,
    "m12_09_00_00": 3,
    "m14_00_00_00": 3,
    "m16_00_00_00": 2,
    "m19_00_00_00": 2,
    "m25_00_00_00": 1,
    "m30_00_00_00": 3,
    "m30_01_00_00": 3,
    "m30_02_00_00": 3,
    "m30_03_00_00": 3,
    "m30_04_00_00": 4,
    "m30_05_00_00": 4,
    "m30_06_00_00": 4,
    "m30_07_00_00": 4,
    "m30_08_00_00": 4,
    "m30_09_00_00": 4,
    "m30_10_00_00": 4,
    "m30_11_00_00": 4,
    "m30_12_00_00": 4,
    "m30_13_00_00": 4,
    "m30_14_00_00": 4,
    "m30_15_00_00": 4,
    "m30_16_00_00": 4,
    "m30_17_00_00": 5,
    "m30_18_00_00": 5,
    "m30_21_00_00": 5,
    "m31_00_00_00": 6,
    "m31_01_00_00": 6,
    "m31_02_00_00": 6,
    "m31_03_00_00": 6,
    "m31_04_00_00": 6,
    "m31_05_00_00": 6,
    "m31_06_00_00": 6,
    "m31_07_00_00": 6,
    "m31_09_00_00": 6,
    "m31_10_00_00": 6,
    "m31_11_00_00": 6,
    "m31_12_00_00": 6,
    "m31_15_00_00": 6,
    "m31_18_00_00": 6,
    "m31_19_00_00": 6,
    "m31_20_00_00": 6,
    "m31_21_00_00": 6,
    "m31_22_00_00": 6,
    "m31_81_00_00": 9,  # DLC / late
    "m31_82_00_00": 9,
    "m32_00_00_00": 7,
    "m32_01_00_00": 7,
    "m32_02_00_00": 7,
    "m32_04_00_00": 7,
    "m32_05_00_00": 7,
    "m32_07_00_00": 7,
    "m32_08_00_00": 7,
    "m32_11_00_00": 7,
    "m34_10_00_00": 9,
    "m34_11_00_00": 9,
    "m34_12_00_00": 9,
    "m34_13_00_00": 9,
    "m34_14_00_00": 9,
    "m34_15_00_00": 9,
    "m35_00_00_00": 5,  # Volcano Manor
    "m39_20_00_00": 9,  # Farum Azula
}

# m30/m31 legacy dungeon prefix fallback when exact id missing.
DUNGEON_PREFIX_TIERS: dict[str, int] = {
    "m30_": 4,
    "m31_": 6,
    "m32_": 7,
    "m34_": 9,
    "m10_": 4,
    "m11_": 2,
    "m12_": 3,
    "m14_": 3,
    "m16_": 2,
    "m19_": 2,
    "m25_": 1,
    "m35_": 5,
    "m39_": 9,
}


def overworld_tile_tier(x: int, y: int) -> int:
    """Approximate ER open-world tile -> progression tier."""
    if y <= 16:
        return 8
    if y <= 20 and x >= 44:
        return 7
    if y <= 24 and 38 <= x <= 52:
        return 6
    if y <= 30 and 34 <= x <= 50:
        return 5
    if x >= 50 and 34 <= y <= 54:
        return 4
    if x <= 34 and 34 <= y <= 52:
        return 3
    if y >= 54:
        return 1
    if y >= 48:
        return 2
    return 5


def resolve_map_tier(map_id: str, *, default_tier: int = 5, dungeon_default: int = 4) -> tuple[int, str]:
    if map_id in DUNGEON_MAP_TIERS:
        return DUNGEON_MAP_TIERS[map_id], "dungeon_exact"
    parts = map_id.split("_")
    if len(parts) >= 4 and parts[0] == "m60":
        try:
            x = int(parts[1], 10)
            y = int(parts[2], 10)
        except ValueError:
            return default_tier, "overworld_parse_fail"
        return overworld_tile_tier(x, y), "overworld_tile"
    for prefix, tier in DUNGEON_PREFIX_TIERS.items():
        if map_id.startswith(prefix):
            return tier, f"dungeon_prefix:{prefix}"
    if parts[0] != "m60":
        return dungeon_default, "dungeon_default"
    return default_tier, "default"


def build(index_path: Path = DEFAULT_INDEX) -> dict:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    map_ids = sorted({str(s.get("map_id", "")) for s in index.get("slots", []) if s.get("map_id")})
    by_map_id: dict[str, int] = {}
    reasons: dict[str, str] = {}
    for mid in map_ids:
        tier, reason = resolve_map_tier(mid)
        by_map_id[mid] = tier
        reasons[mid] = reason
    tier_hist = Counter(by_map_id.values())
    return {
        "schema": "enemy_map_progression_v1",
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_index": str(index_path.name),
        "map_count": len(by_map_id),
        "default_tier": 5,
        "dungeon_default_tier": 4,
        "by_map_id": by_map_id,
        "_build_reasons": reasons,
        "_tier_histogram": {str(k): v for k, v in sorted(tier_hist.items())},
    }


def write_report(payload: dict, report_path: Path) -> None:
    lines = [
        "# 敌人地图进度表",
        "",
        f"- built: {payload.get('built_at')}",
        f"- maps: {payload.get('map_count')}",
        f"- histogram: {payload.get('_tier_histogram')}",
        "",
        "| tier | map_id | reason |",
        "|------|--------|--------|",
    ]
    reasons = payload.get("_build_reasons") or {}
    for mid in sorted(payload.get("by_map_id", {})):
        tier = payload["by_map_id"][mid]
        lines.append(f"| {tier} | `{mid}` | {reasons.get(mid, '')} |")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    payload = build()
    public = {k: v for k, v in payload.items() if not k.startswith("_")}
    OUT_JSON.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(payload, OUTPUT_REPORTS / "敌人地图进度表.md")
    print(f"wrote {OUT_JSON} maps={payload['map_count']} hist={payload['_tier_histogram']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
