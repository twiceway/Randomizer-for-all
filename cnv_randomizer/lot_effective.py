"""CNV lot slot pickup ids when runtime differs from ItemLotParam_map CSV."""

from __future__ import annotations

import json
from pathlib import Path

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
DEFAULT_LOT_EFFECTIVE_PATH = SCRIPT_DIR / "lot_effective_items.json"


def load_lot_effective_items(path: Path | None = None) -> dict[tuple[int, int], int]:
    """(lot_id, slot_index 1-8) -> runtime raw item id seen in give_item."""
    path = path or DEFAULT_LOT_EFFECTIVE_PATH
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[tuple[int, int], int] = {}
    for lot_key, slots in data.items():
        if str(lot_key).startswith("_"):
            continue
        lot_id = int(lot_key)
        if not isinstance(slots, dict):
            continue
        for slot_key, item_id in slots.items():
            slot_idx = int(slot_key)
            runtime_id = int(item_id)
            if lot_id > 0 and 1 <= slot_idx <= 8 and runtime_id > 0:
                out[(lot_id, slot_idx)] = runtime_id
    return out


def resolve_slot_source_item(
    lot_id: int,
    slot_idx: int,
    csv_item_id: int,
    effective_map: dict[tuple[int, int], int] | None = None,
) -> int:
    if csv_item_id <= 0:
        return csv_item_id
    effective_map = effective_map or {}
    return effective_map.get((lot_id, slot_idx), csv_item_id)
