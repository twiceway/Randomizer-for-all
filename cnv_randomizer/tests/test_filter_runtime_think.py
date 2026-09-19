"""filter_prep_donor_indices_for_runtime_think — T-083 pick 预筛。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from donor_vanilla_states import (  # noqa: E402
    build_model_vanilla_state_index,
    filter_prep_donor_indices_for_runtime_think,
)


class FilterRuntimeThinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model_index = build_model_vanilla_state_index(
            [
                {
                    "model": "c4315",
                    "walk_route": "walk_route_c4315_9000_10",
                    "npc": 43151050,
                    "think": 43151001,
                },
                {
                    "model": "c5525",
                    "walk_route": "walk_route_c5525_9000_6",
                    "npc": 55250095,
                    "think": 55250000,
                },
            ]
        )
        self.prep = {
            "donors": [
                {
                    "template_id": "m60_47_57_00:c4315_9000",
                    "model": "c4315",
                    "npc": 43150052,
                    "think": 43150000,
                    "walk_route": "",
                },
                {
                    "template_id": "m61_47_47_00:c5525_9000",
                    "model": "c5525",
                    "npc": 55250095,
                    "think": 55250000,
                    "walk_route": "",
                },
            ]
        }
        self.slot = {
            "walk_route": "walk_route_c4310_9007_20",
            "model": "c4311",
            "npc": 43111210,
            "think": 43111100,
        }

    def test_standing_c4315_passes_family_after_patrol_align(self) -> None:
        out = filter_prep_donor_indices_for_runtime_think(
            self.prep,
            [0],
            self.slot,
            self.model_index,
        )
        self.assertEqual(out, [0])

    def test_quadruped_standing_passes(self) -> None:
        out = filter_prep_donor_indices_for_runtime_think(
            self.prep,
            [1],
            self.slot,
            self.model_index,
        )
        self.assertEqual(out, [1])


if __name__ == "__main__":
    unittest.main()
