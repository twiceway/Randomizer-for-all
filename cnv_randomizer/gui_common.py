#!/usr/bin/env python3
from __future__ import annotations

import json
import locale
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from donor_pool_review_allowlist import migrate_category_weights  # noqa: E402

from paths import (  # noqa: E402
    GAME_DIR,
    OUTPUT_RUNTIME,
    SCRIPT_DIR,
    ensure_output_dirs,
    resolve_output_dir,
)

CONFIG_PATH = SCRIPT_DIR / "config.json"
ENEMY_SPAWN_MAP_PATH = OUTPUT_RUNTIME / "cnv_enemy_spawn_map.txt"


def _decode_subprocess_bytes(data: bytes | None) -> str:
    """Windows 子进程 stdout 常为 GBK；GUI 日志统一解码为可读中文。"""
    if not data:
        return ""
    candidates: list[str] = ["utf-8"]
    pref = locale.getpreferredencoding(False)
    if pref:
        candidates.append(pref)
    for extra in ("gbk", "cp936"):
        if extra not in candidates:
            candidates.append(extra)
    for enc in candidates:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _read_spawn_map_seed(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[:8]:
            if line.startswith("seed="):
                return int(line.split("=", 1)[1].strip())
    except (OSError, ValueError):
        return None
    return None

from cnv_randomizer_core import (  # noqa: E402
    CAT_GOODS,
    NAME_TO_CAT,
    RegionPanelCache,
    build_region_panel_cache,
    build_unified_pool,
    compute_effective_pools,
    deploy_runtime_map,
    load_config,
    load_item_type_index,
    read_csv,
    run_randomize,
    save_config,
)
from goods_subcats import (  # noqa: E402
    GOODS_GROUP_LABELS,
    GOODS_GROUP_ORDER,
    GOODS_GROUP_PRESET_PILLAR,
    GOODS_GROUP_PRESET_SAFE,
    expand_goods_groups,
    load_goods_rows,
    load_goods_subcat_index,
)
from region_tiers import region_display_label  # noqa: E402
from enemy_randomizer_core import (  # noqa: E402
    DEFAULT_INDEX_PATH,
    _ENEMY_CALC_PHASE_SPAN,
    is_dlc_trash_donor_model,
    deploy_enemy_spawn_map,
    run_enemy_apply,
    run_enemy_randomize,
    run_index_export,
    _load_json,
    DEFAULT_CATEGORIES_PATH,
)
from donor_pool_review_allowlist import migrate_category_weights  # noqa: E402
from gui_maintainer import deploy_enemy_debug_slot_index, is_maintainer_gui  # noqa: E402
from gui_session_log import (  # noqa: E402
    GuiSessionLog,
    LATEST_LOG,
    append_enemy_result_diagnostics,
)
from gui_i18n import (  # noqa: E402
    category_labels_map,
    enemy_category_labels_map,
    get_ui_lang,
    set_ui_lang,
    t,
)

CATEGORY_LABELS = category_labels_map()
EQUIP_GUI_SWITCH_ORDER: tuple[str, ...] = ("weapon", "armor", "magic")
ENEMY_CATEGORY_LABELS: dict[str, str] = enemy_category_labels_map()
ENEMY_CATEGORY_ORDER = tuple(ENEMY_CATEGORY_LABELS.keys())


def refresh_gui_label_maps() -> None:
    """Call after set_ui_lang so tabs rebuild with the right words."""
    global CATEGORY_LABELS, ENEMY_CATEGORY_LABELS, ENEMY_NUM_LEGEND
    CATEGORY_LABELS = category_labels_map()
    ENEMY_CATEGORY_LABELS = enemy_category_labels_map()
    ENEMY_NUM_LEGEND = "  ".join(
        f"{ENEMY_CATEGORY_NUM[c]}={ENEMY_CATEGORY_LABELS[c]}"
        for c in ENEMY_CATEGORY_ORDER
    )

ENEMY_CATEGORY_NUM: dict[str, int] = {
    cat_id: idx + 1 for idx, cat_id in enumerate(ENEMY_CATEGORY_ORDER)
}

ENEMY_NUM_LEGEND = "  ".join(
    f"{ENEMY_CATEGORY_NUM[c]}={ENEMY_CATEGORY_LABELS[c]}"
    for c in ENEMY_CATEGORY_ORDER
)


def diagonal_enemy_category_weights() -> dict[str, dict[str, float]]:
    """Preset: 100% on diagonal only (same-category replacement)."""
    return {
        src: {tgt: (100.0 if src == tgt else 0.0) for tgt in ENEMY_CATEGORY_ORDER}
        for src in ENEMY_CATEGORY_ORDER
    }


def default_enemy_category_weights() -> dict[str, dict[str, float]]:
    """Project default 7×7 matrix (%); aligned with 筛选后捐池表 1–7。"""
    return migrate_category_weights(
        {
            "trash": {
                "trash": 86.0,
                "elite": 2.0,
                "minor_boss": 3.0,
                "evergaol": 6.0,
                "night": 2.0,
                "major_boss": 1.0,
            },
            "elite": {"elite": 100.0},
            "minor_boss": {
                "minor_boss": 35.0,
                "evergaol": 26.0,
                "night": 13.0,
                "major_boss": 13.0,
            },
            "evergaol": {
                "evergaol": 55.0,
                "night": 15.0,
                "major_boss": 15.0,
            },
            "night": {"night": 70.0, "major_boss": 15.0, "evergaol": 15.0},
            "major_boss": {"major_boss": 100.0},
        }
    )


def _format_weight(value: float) -> str:
    if value <= 0:
        return "0"
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.1f}"


def load_enemy_category_weights(enemy_cfg: dict) -> dict[str, dict[str, float]]:
    if raw := enemy_cfg.get("category_weights"):
        raw = migrate_category_weights(raw)
        out: dict[str, dict[str, float]] = {}
        for src in ENEMY_CATEGORY_ORDER:
            row_raw = raw.get(src, {})
            if not isinstance(row_raw, dict):
                continue
            row: dict[str, float] = {}
            for tgt in ENEMY_CATEGORY_ORDER:
                try:
                    w = float(row_raw.get(tgt, 0))
                except (TypeError, ValueError):
                    w = 0.0
                if w > 0:
                    row[tgt] = w
            if row:
                out[src] = row
        if out:
            return migrate_category_weights(out)
    if raw := enemy_cfg.get("category_targets"):
        out = {}
        for src in ENEMY_CATEGORY_ORDER:
            chosen = [t for t in raw.get(src, []) if t in ENEMY_CATEGORY_LABELS]
            if not chosen:
                continue
            share = 100.0 / len(chosen)
            out[src] = {t: share for t in chosen}
        if out:
            return migrate_category_weights(out)
    if enabled := enemy_cfg.get("enabled_categories"):
        pool = [c for c in enabled if c in ENEMY_CATEGORY_LABELS]
        if pool:
            share = 100.0 / len(pool)
            return {
                src: {t: share for t in pool}
                for src in ENEMY_CATEGORY_ORDER
            }
    return default_enemy_category_weights()


def normalize_enemy_row_weights(
    row: dict[str, float], *, target_sum: float = 100.0
) -> dict[str, float]:
    positive = {k: v for k, v in row.items() if v > 0}
    if not positive:
        return {}
    total = sum(positive.values())
    if total <= 0:
        return {}
    scale = target_sum / total
    return {k: v * scale for k, v in positive.items()}


def adjust_enemy_row_weights_on_max(
    row: dict[str, float],
    *,
    edited_key: str | None = None,
    target_sum: float = 100.0,
    category_order: tuple[str, ...] = ENEMY_CATEGORY_ORDER,
) -> dict[str, float]:
    """Keep user-entered cells; only the largest cell absorbs the remainder to reach target_sum."""
    values = {k: v for k, v in row.items() if v > 0}
    if not values:
        return {}

    max_val = max(values.values())
    max_keys = [k for k, v in values.items() if v == max_val]
    if edited_key in max_keys:
        max_key = edited_key
    else:
        max_key = next(k for k in category_order if k in max_keys)

    other_sum = sum(v for k, v in values.items() if k != max_key)
    max_new = round(target_sum - other_sum, 1)
    if max_new < 0:
        max_new = 0.0

    out = {k: v for k, v in values.items() if k != max_key}
    if max_new > 0:
        out[max_key] = max_new
    return out


def load_enemy_mob_drop_mode(enemy_cfg: dict) -> str:
    """GUI/runtime default is donor_default (new-foe runes). Legacy keys still parse."""
    mode = enemy_cfg.get("mob_drop_mode")
    if mode in ("keep_original", "donor_default"):
        return mode
    if mode == "rune_by_difficulty":
        return "donor_default"
    legacy = enemy_cfg.get("drop_mode")
    if legacy in ("keep_original", "donor_default"):
        return legacy
    if legacy == "rune_by_difficulty":
        return "donor_default"
    if enemy_cfg.get("keep_original_drops") is False:
        return "donor_default"
    # Default when unset: donor_default (2026-09-15 GUI 精简)
    if "mob_drop_mode" not in enemy_cfg and "drop_mode" not in enemy_cfg:
        return "donor_default"
    if enemy_cfg.get("keep_original_drops") is True:
        return "keep_original"
    return "donor_default"


ENEMY_DLC_POOL_MODE = "mixed"  # 固定混池；2026-07-29 废止 separate / GUI 已删


def load_enemy_difficulty_settings(enemy_cfg: dict) -> dict:
    from enemy_difficulty import normalize_difficulty_settings

    return normalize_difficulty_settings(enemy_cfg)


STRICTNESS_REFRESH_MS = 250
STRICTNESS_SAVE_MS = 600
SESSION_SAVE_MS = 600



