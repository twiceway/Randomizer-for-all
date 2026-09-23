"""Dense-slot density lookup only — no clustering.

Reads cache/enemy_slot_density.json written by build_enemy_slot_density.py.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
DEFAULT_DENSITY_PATH = SCRIPT_DIR / "cache" / "enemy_slot_density.json"
DEFAULT_DENSITY_META_PATH = SCRIPT_DIR / "cache" / "enemy_slot_density.meta.json"
DEFAULT_INDEX_PATH = SCRIPT_DIR / "cache" / "enemy_index.json"

DensityPolicy = Literal["keep_original", "dense_pool_1_2"]
DENSE_POOL_1_2_CATS = frozenset({"trash", "elite"})


def _file_fingerprint(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def clear_density_cache() -> None:
    load_density_payload.cache_clear()
    load_density_meta.cache_clear()


@lru_cache(maxsize=1)
def load_density_meta(
    meta_path: str | None = None,
) -> dict[str, Any] | None:
    path = Path(meta_path) if meta_path else DEFAULT_DENSITY_META_PATH
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


@lru_cache(maxsize=1)
def load_density_payload(
    density_path: str | None = None,
) -> dict[str, Any] | None:
    path = Path(density_path) if density_path else DEFAULT_DENSITY_PATH
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def density_fingerprint_ok(
    *,
    index_path: Path | None = None,
    meta_path: Path | None = None,
) -> tuple[bool, str]:
    """Compare density meta index_fingerprint to current enemy_index.

    Returns (ok, message). Missing density → (False, hint); does not raise.
    """
    meta = load_density_meta(str(meta_path) if meta_path else None)
    if meta is None:
        return False, "缺少 enemy_slot_density.meta.json — 请先「扫描地图」或运行 build_enemy_slot_density.py"
    want = str(meta.get("index_fingerprint") or "")
    idx = index_path or DEFAULT_INDEX_PATH
    if not idx.is_file():
        return False, f"缺少 enemy_index.json：{idx}"
    have = _file_fingerprint(idx)
    if not want:
        return False, "密度库 meta 无 index_fingerprint"
    if want != have:
        return (
            False,
            f"密度库过期（meta={want} index={have}）— 请先「扫描地图」重建",
        )
    return True, "density_fingerprint=ok"


def slot_density_policy(
    map_id: str,
    entity_name: str,
    *,
    density_path: Path | None = None,
) -> DensityPolicy | None:
    """None if not constrained; else keep_original | dense_pool_1_2."""
    payload = load_density_payload(str(density_path) if density_path else None)
    if not payload:
        return None
    slots = payload.get("slots") or {}
    row = slots.get(f"{map_id}:{entity_name}")
    if not isinstance(row, dict):
        return None
    if row.get("keep_original"):
        return "keep_original"
    if row.get("dense_pool_1_2") or row.get("dense_trash_only"):
        # dense_trash_only = 旧字段兼容（现网已改为池1+2）
        return "dense_pool_1_2"
    return None


def restrict_weights_to_pool_1_2(row: dict[str, float]) -> dict[str, float]:
    """Keep only trash/elite; if both zero → trash=100."""
    out = {
        k: float(v)
        for k, v in row.items()
        if k in DENSE_POOL_1_2_CATS and float(v) > 0
    }
    if not out:
        return {"trash": 100.0}
    return out
