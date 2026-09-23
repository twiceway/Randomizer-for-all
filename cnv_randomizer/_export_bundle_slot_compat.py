"""T-084 R1 — export cache/bundle_slot_compat.json (pairing engine + bundle donor compat)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bundle_export_common import export_meta, file_fingerprint, load_enemy_index, slot_key, write_cache_json
from donor_msb_compat import compat_entry_for_template, donor_slot_compat_reject_reason, load_donor_slot_compat
from gatefront_quad_catalog import _load_categories_cfg
from _export_bundle_catalog import build_bundle_catalog

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_JSON = SCRIPT_DIR / "cache" / "bundle_slot_compat.json"
PILOT_MAP = "m60_42_37_00"
PAIRING_ENGINE = "donor_slot_compat_reject_reason_v2"


def _bundle_compat_entries(catalog: dict[str, Any]) -> dict[str, dict]:
    compat_by_tid = load_donor_slot_compat()
    out: dict[str, dict] = {}
    for bid, bundle in (catalog.get("bundles") or {}).items():
        entry = compat_entry_for_template(str(bid), compat_by_tid)
        out[str(bid)] = {
            "bundle_id": bid,
            "src_pool": bundle.get("src_pool"),
            "src_category": bundle.get("src_category"),
            "model": bundle.get("model"),
            "compat": entry,
        }
    return out


def _pilot_pairing_samples(
    index: dict[str, Any],
    bundle_ids: list[str],
    categories_cfg: dict[str, Any],
    compat_by_tid: dict[str, dict[str, Any]],
) -> dict[str, dict[str, str | None]]:
    """Pilot map: slot_key -> bundle_id -> reject reason (None = allow)."""
    slots = [
        s
        for s in index.get("slots") or []
        if str(s.get("map_id") or "") == PILOT_MAP
    ]
    samples: dict[str, dict[str, str | None]] = {}
    for slot in slots:
        sk = slot_key(slot)
        per: dict[str, str | None] = {}
        for bid in bundle_ids:
            reason = donor_slot_compat_reject_reason(
                slot,
                bid,
                categories_cfg=categories_cfg,
                compat_by_tid=compat_by_tid,
            )
            per[bid] = reason
        samples[sk] = per
    return samples


def build_bundle_slot_compat(
    index: dict | None = None,
    catalog: dict | None = None,
) -> dict:
    index = index or load_enemy_index()
    categories_cfg = _load_categories_cfg()
    if catalog is None:
        catalog = build_bundle_catalog(index)
    compat_by_tid = load_donor_slot_compat()
    bundle_ids = sorted(str(k) for k in (catalog.get("bundles") or {}).keys())
    meta = export_meta(
        extra_fingerprints={
            "bundle_catalog": file_fingerprint(SCRIPT_DIR / "cache" / "bundle_catalog.json"),
            "slot_tags": file_fingerprint(SCRIPT_DIR / "cache" / "slot_tags.json"),
            "donor_slot_compat": file_fingerprint(SCRIPT_DIR / "cache" / "donor_slot_compat.json"),
        }
    )
    return {
        **meta,
        "pairing_engine": PAIRING_ENGINE,
        "pilot_map_id": PILOT_MAP,
        "bundle_count": len(bundle_ids),
        "bundles": _bundle_compat_entries(catalog),
        "pilot_pairings": _pilot_pairing_samples(
            index, bundle_ids, categories_cfg, compat_by_tid
        ),
    }


def main() -> None:
    catalog_path = SCRIPT_DIR / "cache" / "bundle_catalog.json"
    slot_tags_path = SCRIPT_DIR / "cache" / "slot_tags.json"
    if not catalog_path.is_file():
        from _export_bundle_catalog import main as export_catalog

        export_catalog()
    if not slot_tags_path.is_file():
        from _export_slot_tags import main as export_tags

        export_tags()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    payload = build_bundle_slot_compat(catalog=catalog)
    write_cache_json(CACHE_JSON, payload)
    print(
        f"Wrote {CACHE_JSON} bundles={payload['bundle_count']} "
        f"pilot_slots={len(payload.get('pilot_pairings') or {})}"
    )


if __name__ == "__main__":
    main()
