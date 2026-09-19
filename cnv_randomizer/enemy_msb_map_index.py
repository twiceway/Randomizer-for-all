"""Per-map MSB model-name indexes (apply hot path + future randomizers).

Sources are split by game/mod lineage — only CNV (法魂) is implemented today.
"""
from __future__ import annotations

from pathlib import Path

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
CACHE_ROOT = SCRIPT_DIR / "cache" / "msb_map_model_index"

# Active index sources. Add keys here when vanilla / other-mod randomizers land.
MSB_MAP_MODEL_INDEX_SOURCES: dict[str, str] = {
    "cnv": "法魂 Convergence 地图 MSB（当前敌人随机器）",
    # "vanilla": "原版 Elden Ring",
    # "mod_xyz": "其它 MOD",
}

SCHEMA_V1 = "msb_map_model_index_v1"


def map_model_index_path(source: str = "cnv") -> Path:
    if source not in MSB_MAP_MODEL_INDEX_SOURCES:
        raise KeyError(f"unknown msb map model index source: {source}")
    return CACHE_ROOT / source / "map_model_names.json"
