"""T-093: whitelist effective HP lookup for difficulty baseline."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
REPO_ROOT = SCRIPT_DIR.parent
WHITELIST_JSON = REPO_ROOT / "捐皮契约" / "捐皮白名单_当前.json"


@lru_cache(maxsize=1)
def load_whitelist_effective_hp_index() -> dict[str, int]:
    """model prefix → max effective_hp from whitelist rows."""
    if not WHITELIST_JSON.is_file():
        return {}
    data = json.loads(WHITELIST_JSON.read_text(encoding="utf-8-sig"))
    by_model: dict[str, int] = {}
    pool_bags = data.get("rows_by_pool") or data.get("pools") or {}
    for pool_rows in pool_bags.values():
        if not isinstance(pool_rows, list):
            continue
        for row in pool_rows:
            model = str(row.get("model") or "").lower()
            try:
                eff = int(row.get("effective_hp") or 0)
            except (TypeError, ValueError):
                eff = 0
            if not model or eff <= 0:
                continue
            by_model[model] = max(by_model.get(model, 0), eff)
    return by_model


def whitelist_effective_hp_for_model(model: str) -> int | None:
    model_l = (model or "").lower()
    if not model_l:
        return None
    table = load_whitelist_effective_hp_index()
    best = 0
    for prefix, eff in table.items():
        if model_l.startswith(prefix.lower()):
            best = max(best, eff)
    return best if best > 0 else None


def resolve_donor_baseline_effective_hp(
    row: dict[str, Any],
    donor_row: dict[str, str] | None,
    *,
    npc_by_id: dict[int, dict[str, str]] | None = None,
) -> int:
    """白名单有效血优先；否则 NpcParam 审阅口径。"""
    model = str(row.get("model") or "")
    wl = whitelist_effective_hp_for_model(model)
    if wl is not None and wl > 0:
        return wl
    if donor_row is None:
        return 0
    from dlc_donor_pool import load_sp_hp_rates, npc_effective_hp_for_review

    try:
        npc = int(row.get("npc") or 0)
    except (TypeError, ValueError):
        npc = 0
    sp_rates = load_sp_hp_rates()
    pick = npc_effective_hp_for_review(
        npc,
        donor_row,
        model=model,
        sp_rates=sp_rates,
        npc_by_id=npc_by_id,
    )
    return max(0, int(pick.get("effective_hp") or 0))
