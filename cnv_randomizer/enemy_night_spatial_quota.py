"""T-066 / T-069: spatial quotas for night red spirits and major_boss picks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NightSpatialQuotaConfig:
    enabled: bool
    cell_xz: float
    cell_y: float
    max_per_cell: int


def load_night_spatial_quota_config(
    categories_cfg: dict[str, Any],
) -> NightSpatialQuotaConfig:
    return _load_spatial_quota_config(categories_cfg, "night_spatial_quota")


def load_major_boss_spatial_quota_config(
    categories_cfg: dict[str, Any],
) -> NightSpatialQuotaConfig:
    """T-069：6 池 major_boss 空间配额（默认 500×500×500 m）。"""
    return _load_spatial_quota_config(categories_cfg, "major_boss_spatial_quota")


def _load_spatial_quota_config(
    categories_cfg: dict[str, Any],
    key: str,
) -> NightSpatialQuotaConfig:
    raw = categories_cfg.get(key) or {}
    if not isinstance(raw, dict):
        raw = {}
    enabled = raw.get("enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() not in ("false", "0", "no")
    cell_xz = float(raw.get("cell_xz", 300) or 300)
    cell_y = float(raw.get("cell_y", 300) or 300)
    max_per_cell = int(raw.get("max_per_cell", 1) or 1)
    return NightSpatialQuotaConfig(
        enabled=bool(enabled),
        cell_xz=max(cell_xz, 1.0),
        cell_y=max(cell_y, 1.0),
        max_per_cell=max(max_per_cell, 1),
    )


def night_spatial_cell_key(
    map_id: str,
    slot: dict[str, Any],
    cfg: NightSpatialQuotaConfig,
) -> tuple[str | int, ...] | None:
    try:
        x = float(slot["pos_x"])
        y = float(slot["pos_y"])
        z = float(slot["pos_z"])
    except (KeyError, TypeError, ValueError):
        return None
    cell = (
        math.floor(x / cfg.cell_xz),
        math.floor(y / cfg.cell_y),
        math.floor(z / cfg.cell_xz),
    )
    # 开放世界 m60/m61：按世界坐标落格（跨图块共享配额）；洞窟/室内仍按 map_id 隔离
    if str(map_id).startswith(("m60_", "m61_")):
        return ("ow", *cell)
    return (map_id, *cell)


def night_cell_at_capacity(
    cell_key: tuple[str | int, ...] | None,
    used: dict[tuple[str | int, ...], int],
    cfg: NightSpatialQuotaConfig,
) -> bool:
    if cell_key is None:
        return False
    return used.get(cell_key, 0) >= cfg.max_per_cell


def record_night_cell_use(
    cell_key: tuple[str | int, ...] | None,
    used: dict[tuple[str | int, ...], int],
) -> None:
    if cell_key is None:
        return
    used[cell_key] = used.get(cell_key, 0) + 1


def major_boss_spatial_cell_key(
    map_id: str,
    slot: dict[str, Any],
    cfg: NightSpatialQuotaConfig,
    *,
    categories_cfg: dict[str, Any] | None = None,
) -> tuple[str | int, ...] | None:
    """T-069：洞窟/室内整图 1 格（避免 x=0 两侧误拆两格）；m60/m61 按 cell_xz/cell_y 世界格。"""
    from boss_npc_detect import dungeon_boss_map_id_prefixes

    mid = str(map_id or "")
    prefixes = dungeon_boss_map_id_prefixes(categories_cfg)
    if prefixes and any(mid.startswith(p) for p in prefixes):
        return (mid,)
    return night_spatial_cell_key(map_id, slot, cfg)
