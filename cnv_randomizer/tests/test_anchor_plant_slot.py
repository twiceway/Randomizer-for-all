"""Anchor plant slots (c4481/c4483) reject non-plant donors."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_category_rules import donor_blocked_for_anchor_plant_slot  # noqa: E402
from enemy_pool_filters import (  # noqa: E402
    filter_pool_for_anchor_plant_slot,
    filter_prep_donor_indices_for_anchor_plant,
)


class TestAnchorPlantSlot(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cfg_path = SCRIPT_DIR / "enemy_categories.json"
        cls.cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))

    def test_demi_human_blocked_on_c4481(self) -> None:
        self.assertTrue(
            donor_blocked_for_anchor_plant_slot("c4481", "c4100", self.cfg)
        )

    def test_miranda_sprout_allowed(self) -> None:
        self.assertFalse(
            donor_blocked_for_anchor_plant_slot("c4481", "c4483", self.cfg)
        )

    def test_filter_pool_rejects_humanoid(self) -> None:
        slot = {"map_id": "m60_44_36_00", "model": "c4481", "name": "c4481_9029"}
        pool = [
            {"model": "c4100", "npc": 41000032},
            {"model": "c4483", "npc": 44830032},
        ]
        out = filter_pool_for_anchor_plant_slot(pool, slot, self.cfg)
        models = {str(t["model"]) for t in out}
        self.assertIn("c4483", models)
        self.assertNotIn("c4100", models)

    def test_filter_prep_indices(self) -> None:
        slot = {"model": "c4481", "name": "c4481_9005"}
        prep = {
            "donors": [
                {"model": "c4100"},
                {"model": "c4482"},
            ]
        }
        out = filter_prep_donor_indices_for_anchor_plant(
            prep, [0, 1], slot, self.cfg
        )
        self.assertEqual(out, [1])


if __name__ == "__main__":
    unittest.main()
