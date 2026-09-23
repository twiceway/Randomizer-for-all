"""T-084 R1 — export cache/slot_tags.json from enemy_index slots."""
from __future__ import annotations

import json
from pathlib import Path

from _export_slot_initial_state import apply_slot_class, is_patrol, placement_kind
from bundle_export_common import export_meta, load_enemy_index, slot_key, write_cache_json
from gatefront_quad_catalog import _load_categories_cfg
from enemy_randomizer_core import (
    compact_slot_tiers,
    effective_slot_map_kind,
    narrow_map_kinds,
    resolve_size_tier,
)
from whitelist_slot_receptor import classify_receptor_bucket

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_JSON = SCRIPT_DIR / "cache" / "slot_tags.json"
REPORT_JSON = SCRIPT_DIR.parent / "reports" / "SlotTags槽位标签全表.json"


def _exclude_large(slot: dict, categories_cfg: dict) -> bool:
    size_map = categories_cfg.get("size_tier_by_model_prefix", {})
    slot_tier = resolve_size_tier(str(slot.get("model", "")), size_map)
    compact = slot_tier in compact_slot_tiers(categories_cfg)
    map_k = effective_slot_map_kind(slot, categories_cfg)
    narrow = map_k in narrow_map_kinds(categories_cfg)
    return compact or narrow


def build_slot_tags(index: dict | None = None) -> dict:
    index = index or load_enemy_index()
    categories_cfg = _load_categories_cfg()
    tags_by_slot: dict[str, dict] = {}
    for slot in index.get("slots") or []:
        key = slot_key(slot)
        bucket = classify_receptor_bucket(slot)
        tags_by_slot[key] = {
            "map_id": str(slot.get("map_id") or ""),
            "entity": str(slot.get("name") or ""),
            "src_cat": str(
                slot.get("src_cat")
                or (slot.get("slot_tags") or {}).get("src_cat")
                or ""
            ),
            "receptor_bucket": bucket,
            "slot_msb_class": apply_slot_class(slot),
            "placement_kind": placement_kind(slot),
            "has_walk_route": bool(str(slot.get("walk_route") or "").strip()),
            "exclude_large": _exclude_large(slot, categories_cfg),
            "is_patrol": is_patrol(slot),
            "model": str(slot.get("model") or ""),
        }
    meta = export_meta()
    return {
        **meta,
        "index_generated_at": index.get("generated_at"),
        "slot_count": len(tags_by_slot),
        "slots": tags_by_slot,
    }


def main() -> None:
    payload = build_slot_tags()
    write_cache_json(CACHE_JSON, payload)
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {CACHE_JSON} slots={payload['slot_count']}")
    print(f"Wrote {REPORT_JSON}")


if __name__ == "__main__":
    main()
