"""T-098 supersedes T-097b auto-tail exempt tests: auto-tail is abolished."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_donor_pick import identify_structural_tail_npcs  # noqa: E402


class TestStructuralTailExempt(unittest.TestCase):
    def test_boss_low_cap_not_auto_tail_medium_is(self) -> None:
        # T-098: nothing auto-tails, including former medium low-cap.
        npc_slot_cap = {
            530000: 127,
            582000: 122,
            476000: 90,
            999000: 50,
        }
        donors = [
            {"npc": 530000, "model": "c5300"},
            {"npc": 582000, "model": "c5820"},
            {"npc": 476000, "model": "c4760"},
            {"npc": 999000, "model": "c0100"},
        ]
        categories_cfg = {
            "pool_npc_structural_tail_ratio": 0.2,
            "pool_npc_structural_tail_min_slots": 5,
            "pool_npc_structural_tail_max_cap_ratio": 0.78,
            "pool_npc_structural_tail_npcs": {},
            "pool_npc_structural_tail_exempt_size_tiers": [
                "large",
                "colossal",
                "boss",
            ],
            "size_tier_by_model_prefix": {
                "c5300": "boss",
                "c5820": "medium",
                "c4760": "boss",
                "c0100": "medium",
            },
        }
        tail = identify_structural_tail_npcs(
            npc_slot_cap, categories_cfg, "major_boss", donors=donors
        )
        self.assertEqual(tail, set())

    def test_manual_tail_still_forces_boss(self) -> None:
        npc_slot_cap = {476000: 90, 530000: 127}
        donors = [
            {"npc": 476000, "model": "c4760"},
            {"npc": 530000, "model": "c5300"},
        ]
        categories_cfg = {
            "pool_npc_structural_tail_npcs": {"major_boss": {"476000": True}},
            "pool_npc_structural_tail_exempt_size_tiers": [
                "large",
                "colossal",
                "boss",
            ],
            "size_tier_by_model_prefix": {
                "c4760": "boss",
                "c5300": "boss",
            },
        }
        tail = identify_structural_tail_npcs(
            npc_slot_cap, categories_cfg, "major_boss", donors=donors
        )
        self.assertIn(476000, tail)


if __name__ == "__main__":
    unittest.main()
