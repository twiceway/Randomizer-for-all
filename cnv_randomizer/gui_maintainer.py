"""Maintainer-only GUI affordances — hidden unless explicitly enabled."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
MAINTAINER_LOCAL_PATH = SCRIPT_DIR / "maintainer.local.json"
DEBUG_SLOTS_CACHE = SCRIPT_DIR / "cache" / "cnv_enemy_debug_slots.txt"


def is_maintainer_gui(cfg: dict | None = None) -> bool:
    """Release builds default False; enable via config, local file, or env."""
    env = os.environ.get("CNV_MAINTAINER_GUI", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if MAINTAINER_LOCAL_PATH.is_file():
        try:
            local = json.loads(MAINTAINER_LOCAL_PATH.read_text(encoding="utf-8"))
            if local.get("maintainer_gui") is True:
                return True
        except (OSError, json.JSONDecodeError):
            pass
    if cfg and cfg.get("maintainer_gui") is True:
        return True
    return False


def deploy_enemy_debug_slot_index(*, game_dir: Path) -> tuple[Path, int]:
    """Export MSB slot index for hook F6/F7 nearest-slot resolve → mod/dll."""
    from export_enemy_debug_slots import main as export_main

    rc = export_main()
    if rc != 0:
        raise RuntimeError("F6/F7 槽位索引导出失败（需先扫描游戏地图）")
    if not DEBUG_SLOTS_CACHE.is_file():
        raise FileNotFoundError(DEBUG_SLOTS_CACHE)
    slot_count = sum(
        1
        for line in DEBUG_SLOTS_CACHE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    dst_dir = game_dir / "mod" / "dll"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "cnv_enemy_debug_slots.txt"
    shutil.copy2(DEBUG_SLOTS_CACHE, dst)
    return dst, slot_count
