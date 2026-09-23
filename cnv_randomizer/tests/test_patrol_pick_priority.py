"""Pick-time patrol donor preference (prep donor walk_route / compat)."""

from __future__ import annotations

import unittest

from donor_vanilla_states import prioritize_patrol_donor_indices


class PatrolDonorPickPriorityTests(unittest.TestCase):
    def test_patrol_slot_prefers_patrol_origin_donor(self) -> None:
        prep = {
            "donors": [
                {
                    "template_id": "m60_49_57_00:c3180_9000",
                    "model": "c3180",
                    "walk_route": "",
                },
                {
                    "template_id": "m60_35_50_00:c3180_9002",
                    "model": "c3180",
                    "walk_route": "walk_route_c3180_9002_6",
                },
            ],
        }
        slot = {"walk_route": "walk_route_c4310_9007_20"}
        out = prioritize_patrol_donor_indices(prep, [0, 1], slot)
        self.assertEqual(out, [1, 0])

    def test_stand_slot_keeps_order(self) -> None:
        prep = {
            "donors": [
                {"template_id": "a", "walk_route": ""},
                {"template_id": "b", "walk_route": "route"},
            ],
        }
        slot = {"walk_route": ""}
        out = prioritize_patrol_donor_indices(prep, [0, 1], slot)
        self.assertEqual(out, [0, 1])


if __name__ == "__main__":
    unittest.main()
