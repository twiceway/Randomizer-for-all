"""T-084 R1 — pilot map pairing parity vs donor_slot_compat_reject_reason."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from donor_msb_compat import donor_slot_compat_reject_reason, load_donor_slot_compat  # noqa: E402
from gatefront_quad_catalog import _load_categories_cfg  # noqa: E402
INDEX_PATH = SCRIPT_DIR / "cache" / "enemy_index.json"
COMPAT_CACHE = SCRIPT_DIR / "cache" / "bundle_slot_compat.json"
PILOT_MAP = "m60_42_37_00"


def test_pilot_pairings_match_live_reject_reason() -> None:
    if not COMPAT_CACHE.is_file():
        return
    raw = json.loads(INDEX_PATH.read_text(encoding="utf-8-sig"))
    slots = [
        s
        for s in raw.get("slots") or []
        if str(s.get("map_id") or "") == PILOT_MAP
    ]
    payload = json.loads(COMPAT_CACHE.read_text(encoding="utf-8"))
    pilot = payload.get("pilot_pairings") or {}
    categories_cfg = _load_categories_cfg()
    compat_by_tid = load_donor_slot_compat()
    mismatches: list[str] = []
    for slot in slots:
        sk = f"{slot.get('map_id')}:{slot.get('name')}"
        cached = pilot.get(sk) or {}
        for bid, cached_reason in cached.items():
            live = donor_slot_compat_reject_reason(
                slot,
                bid,
                categories_cfg=categories_cfg,
                compat_by_tid=compat_by_tid,
            )
            if live != cached_reason:
                mismatches.append(f"{sk} x {bid}: cache={cached_reason!r} live={live!r}")
    assert not mismatches, "pairing mismatches:\n" + "\n".join(mismatches[:20])
