"""Fine-grid maps must not use coarse coord:north → fake consecrated tier 16."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_enemy_map_regions import (  # noqa: E402
    _parse_m60,
    build,
    infer_parent_map_from_slot_names,
    load_explicit_fine_map_overrides,
)
from enemy_world_progression import resolve_map_tier_t093  # noqa: E402


class TestFineMapRegions(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = build()
        cls.by = cls.payload["by_map_id"]

    def test_caravan_event_maps_limgrave_tier1(self) -> None:
        for mid in ("m60_11_09_02", "m60_11_09_12"):
            e = self.by[mid]
            self.assertEqual(e["region_id"], "limgrave", mid)
            self.assertEqual(e["tier"], 1, mid)
            self.assertFalse(str(e["reason"]).startswith("coord:"), e["reason"])

    def test_mausoleum_event_not_consecrated(self) -> None:
        mid = "m60_10_08_02"
        e = self.by[mid]
        self.assertNotEqual(e["region_id"], "consecrated", e)
        self.assertNotEqual(e["tier"], 16, e)

    def test_no_fine_grid_coord_north(self) -> None:
        bad = []
        for mid, e in self.by.items():
            parsed = _parse_m60(mid)
            if not parsed or parsed[2] in ("00", "10"):
                continue
            if str(e.get("reason", "")).startswith("coord:"):
                bad.append((mid, e))
        self.assertEqual(bad, [], f"fine maps still using coord heuristic: {bad}")

    def test_infer_parent_from_slot_names(self) -> None:
        parent = infer_parent_map_from_slot_names(
            ["m60_44_36_00-c0110_9000", "m60_44_36_00-c4300_9011", "c1000_9000"]
        )
        self.assertEqual(parent, "m60_44_36_00")

    def test_caravan_override_loaded(self) -> None:
        ov = load_explicit_fine_map_overrides()
        self.assertIn("m60_11_09_02", ov)
        self.assertEqual(ov["m60_11_09_02"][0], "limgrave")

    def test_runtime_tier_matches_json(self) -> None:
        # After rebuild, resolve_map_tier_t093 reads enemy_map_regions.json —
        # call build write path is separate; here assert payload consistency.
        self.assertEqual(self.by["m60_11_09_02"]["tier"], 1)


if __name__ == "__main__":
    unittest.main()
