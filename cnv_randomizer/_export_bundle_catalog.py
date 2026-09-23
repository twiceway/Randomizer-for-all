"""T-084 R1 — export cache/bundle_catalog.json from enemy_index + whitelist."""
from __future__ import annotations

import json
from pathlib import Path

from bundle_export_common import (
    INDEX_PATH,
    export_meta,
    iter_whitelist_bundle_rows,
    load_enemy_index,
    write_cache_json,
)
from donor_msb_compat import compat_entry_for_template, load_donor_slot_compat
from gatefront_quad_catalog import _load_categories_cfg
from donor_vanilla_states import attach_vanilla_state_fields, build_model_vanilla_state_index
from enemy_randomizer_core import donor_physique_bucket, infer_size_tier, is_oversize_boss_model
from bundle_export_common import file_fingerprint

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_JSON = SCRIPT_DIR / "cache" / "bundle_catalog.json"
REPORT_JSON = SCRIPT_DIR.parent / "reports" / "Bundle捐皮档案全表.json"


def _behavior_profile(donor_row: dict) -> str:
    pose = str(donor_row.get("donor_pose_label") or "")
    if pose in {"patrol"}:
        return "patrol"
    if pose in {"ground_stand"}:
        return "ground_stand"
    if pose in {"aerial_model"} or pose.startswith("aerial"):
        return "fly"
    if pose in {"sit", "squat"}:
        return "sit"
    if pose.startswith("collision_anchor"):
        return "perch"
    kind = str(donor_row.get("donor_placement_kind") or "")
    if kind == "patrol":
        return "patrol"
    if kind == "aerial_model":
        return "fly"
    return "script" if donor_row.get("force_donor_msb") else "ground_stand"


def _bundle_tags(donor_row: dict, compat: dict, categories_cfg: dict) -> list[str]:
    tags: list[str] = []
    model = str(donor_row.get("model") or "").lower()
    size_map = categories_cfg.get("size_tier_by_model_prefix", {})
    tier = infer_size_tier(model, size_map)
    if tier in {"large", "tall", "boss", "mounted"}:
        tags.append("large")
    if is_oversize_boss_model(model):
        tags.append("large")
    if donor_row.get("force_donor_msb"):
        tags.append("force_msb")
    phys = donor_physique_bucket(
        {"model": model, "template_tags": donor_row.get("template_tags") or {}},
        categories_cfg,
        None,
    )
    if phys == "flying":
        tags.append("fly")
    if phys == "quadruped":
        tags.append("quadruped")
    buckets = compat.get("vanilla_supported_buckets") or []
    if "ground_stand" in buckets and "patrol" not in buckets:
        if not str(compat.get("donor_walk_route") or "").strip():
            tags.append("ground_stand_only")
    return sorted(set(tags))


def build_bundle_catalog(index: dict | None = None) -> dict:
    index = index or load_enemy_index()
    categories_cfg = _load_categories_cfg()
    compat_by_tid = load_donor_slot_compat()
    model_index = build_model_vanilla_state_index(list(index.get("slots") or []))

    bundles: dict[str, dict] = {}
    unresolved = 0
    for row in iter_whitelist_bundle_rows(index, categories_cfg):
        if not row.get("resolve_ok") or not row.get("bundle_id"):
            unresolved += 1
            continue
        bid = str(row["bundle_id"])
        tpl = row["template"]
        dr = row["donor_row"]
        compat = compat_entry_for_template(bid, compat_by_tid)
        compat_full = attach_vanilla_state_fields(
            dict(compat),
            str(dr.get("model") or ""),
            model_index,
        )
        bundles[bid] = {
            "bundle_id": bid,
            "model": str(dr.get("model") or ""),
            "npc": dr.get("npc"),
            "think": dr.get("think"),
            "chara": dr.get("chara"),
            "src_pool": int(row.get("pool") or 0),
            "src_category": str(row.get("category") or ""),
            "name_en": row.get("name_en") or "",
            "name_zh": row.get("name_zh") or "",
            "behavior_profile": _behavior_profile(dr),
            "physique": donor_physique_bucket(tpl, categories_cfg, compat_by_tid),
            "tags": _bundle_tags(dr, compat_full, categories_cfg),
            "vanilla_buckets": list(compat_full.get("vanilla_supported_buckets") or []),
            "donor_pose_label": str(compat_full.get("donor_pose_label") or ""),
            "donor_walk_route": str(compat_full.get("donor_walk_route") or ""),
            "force_donor_msb": bool(compat_full.get("force_donor_msb")),
            "compat_standing_keep": compat_full.get("compat_standing_keep"),
            "compat_patrol_keep": compat_full.get("compat_patrol_keep"),
        }

    meta = export_meta(
        extra_fingerprints={
            "donor_slot_compat": file_fingerprint(
                SCRIPT_DIR / "cache" / "donor_slot_compat.json"
            ),
        }
    )
    return {
        **meta,
        "index_generated_at": index.get("generated_at"),
        "bundle_count": len(bundles),
        "unresolved_whitelist_rows": unresolved,
        "bundles": bundles,
    }


def main() -> None:
    if not (SCRIPT_DIR / "cache" / "donor_slot_compat.json").is_file():
        print("WARN: run _export_donor_msb_state.py first")
        from _export_donor_msb_state import main as export_msb

        export_msb()

    payload = build_bundle_catalog()
    write_cache_json(CACHE_JSON, payload)
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {CACHE_JSON} bundles={payload['bundle_count']}")
    print(f"Wrote {REPORT_JSON}")


if __name__ == "__main__":
    main()
