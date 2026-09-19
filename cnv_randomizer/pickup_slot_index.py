"""MSB treasure placements → pickup shuffle slot list (T-064)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import GAME_DIR, SCRIPT_DIR

PICKUP_INDEX_VERSION = 1
DEFAULT_PICKUP_INDEX_PATH = SCRIPT_DIR / "cache" / "pickup_slot_index.json"
DEFAULT_INTERIOR_PREFIXES = (
    "m10_00_",
    "m10_01_",
    "m12_01_",
    "m12_02_",
    "m12_07_",
    "m12_08_",
    "m12_09_",
    "m14_",
    "m15_",
    "m16_",
    "m30_",
    "m31_",
    "m35_",
)
MSB_ENEMY_POC_PROJECT = SCRIPT_DIR.parent / "cnv_enemy_poc" / "MsbEnemyPoc" / "MsbEnemyPoc.csproj"


def default_interior_map_prefixes() -> tuple[str, ...]:
    path = SCRIPT_DIR / "enemy_categories.json"
    if not path.exists():
        return DEFAULT_INTERIOR_PREFIXES
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("interior_map_id_prefixes") or []
    out = tuple(str(p) for p in raw if str(p).strip())
    return out or DEFAULT_INTERIOR_PREFIXES


def load_pickup_slot_index(path: Path | None = None) -> dict[str, Any] | None:
    path = path or DEFAULT_PICKUP_INDEX_PATH
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def is_interior_pickup_map(map_id: str, prefixes: tuple[str, ...] | None = None) -> bool:
    prefixes = prefixes or default_interior_map_prefixes()
    return any(map_id.startswith(p) for p in prefixes)


def resolve_pickup_region_mode(cfg: dict) -> str:
    mode = str(cfg.get("pickup_region_mode", "hybrid")).strip().lower()
    if mode in {"per_map", "canonical", "hybrid"}:
        return mode
    return "hybrid"


def resolve_placement_region_key(
    map_id: str,
    lot_id: int,
    row: dict[str, str],
    cfg: dict,
    lot_regions: dict[int, str] | None = None,
) -> str:
    mode = resolve_pickup_region_mode(cfg)
    if mode == "per_map":
        return map_id
    if mode == "canonical":
        from region_tiers import lot_region_key

        return lot_region_key(row, lot_id)
    prefixes = tuple(cfg.get("pickup_interior_map_id_prefixes") or default_interior_map_prefixes())
    if is_interior_pickup_map(map_id, prefixes):
        return map_id
    if lot_regions and lot_id in lot_regions:
        return lot_regions[lot_id]
    from region_tiers import lot_region_key

    return lot_region_key(row, lot_id)


def run_pickup_index_export(
    game_dir: Path | None = None,
    out_path: Path | None = None,
    max_maps: int = 0,
) -> Path:
    game_dir = game_dir or GAME_DIR
    out_path = out_path or DEFAULT_PICKUP_INDEX_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["dotnet", "build", str(MSB_ENEMY_POC_PROJECT), "-c", "Release"],
        check=True,
        cwd=str(MSB_ENEMY_POC_PROJECT.parent.parent),
    )
    args = [
        "dotnet",
        "run",
        "--project",
        str(MSB_ENEMY_POC_PROJECT),
        "-c",
        "Release",
        "--",
        "pickup-index-export",
        f"--out={out_path}",
    ]
    if max_maps > 0:
        args.append(f"--max-maps={max_maps}")
    proc = subprocess.run(
        args,
        cwd=str(MSB_ENEMY_POC_PROJECT.parent.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        detail = (proc.stdout or "") + (proc.stderr or "")
        raise RuntimeError(f"pickup-index-export failed ({proc.returncode}): {detail[-4000:]}")
    return out_path


def export_pickup_index_if_missing(
    game_dir: Path | None = None,
    out_path: Path | None = None,
) -> Path:
    out_path = out_path or DEFAULT_PICKUP_INDEX_PATH
    if out_path.exists():
        return out_path
    subprocess.run(
        [
            "dotnet",
            "build",
            str(MSB_ENEMY_POC_PROJECT),
            "-c",
            "Release",
        ],
        check=True,
        cwd=str(MSB_ENEMY_POC_PROJECT.parent.parent),
    )
    return run_pickup_index_export(game_dir=game_dir, out_path=out_path)


def placements_for_map(index: dict[str, Any], map_filter: str | None = None) -> list[dict[str, Any]]:
    placements = index.get("placements") or []
    if not map_filter:
        return list(placements)
    return [p for p in placements if str(p.get("map_id", "")) == map_filter]


def lot_ids_for_region(
    placements: list[dict[str, Any]],
    region_key: str,
    rows_by_lot: dict[int, dict[str, str]],
    cfg: dict,
    lot_regions: dict[int, str] | None = None,
) -> set[int]:
    lot_ids: set[int] = set()
    for placement in placements:
        map_id = str(placement.get("map_id", ""))
        lot_id = int(placement.get("lot_id", 0) or 0)
        if lot_id <= 0:
            continue
        row = rows_by_lot.get(lot_id)
        if not row:
            continue
        key = resolve_placement_region_key(map_id, lot_id, row, cfg, lot_regions)
        if key == region_key:
            lot_ids.add(lot_id)
    return lot_ids


def build_region_lot_index(
    placements: list[dict[str, Any]],
    rows_by_lot: dict[int, dict[str, str]],
    cfg: dict,
    lot_regions: dict[int, str] | None = None,
) -> dict[str, set[int]]:
    region_lots: dict[str, set[int]] = {}
    for placement in placements:
        map_id = str(placement.get("map_id", ""))
        lot_id = int(placement.get("lot_id", 0) or 0)
        if lot_id <= 0:
            continue
        row = rows_by_lot.get(lot_id)
        if not row:
            continue
        region_key = resolve_placement_region_key(map_id, lot_id, row, cfg, lot_regions)
        region_lots.setdefault(region_key, set()).add(lot_id)
    return region_lots


def pickup_index_fingerprint(index: dict[str, Any] | None) -> str:
    if not index:
        return ""
    return (
        f"v={index.get('version', 0)}"
        f"|maps={index.get('maps_scanned', 0)}"
        f"|treasures={index.get('treasure_events', 0)}"
        f"|placements={len(index.get('placements') or [])}"
    )


def index_is_stale(cfg: dict, index: dict[str, Any] | None) -> bool:
    if not index:
        return True
    want = int(cfg.get("pickup_index_version", PICKUP_INDEX_VERSION))
    have = int(index.get("version", 0) or 0)
    return have != want
