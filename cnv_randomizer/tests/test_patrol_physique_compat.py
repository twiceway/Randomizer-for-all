"""Patrol humanoid slots may accept quadruped donors (T-076 case A/C)."""

from __future__ import annotations

import unittest

from enemy_randomizer_core import filter_prep_donor_indices_for_physique_compat


class PatrolPhysiqueCompatTests(unittest.TestCase):
    def test_humanoid_patrol_slot_accepts_quadruped_donor(self) -> None:
        prep = {
            "donors": [
                {"model": "c3180", "template_id": "m60_49_57_00:c3180_9000"},
                {"model": "c4311", "template_id": "m60_42_37_00:c4311_9005"},
            ],
        }
        slot = {
            "model": "c4311",
            "walk_route": "walk_route_c4310_9007_20",
        }
        out = filter_prep_donor_indices_for_physique_compat(
            prep,
            [0],
            slot,
            {"quadruped_slot_model_prefixes": ["c3180", "c5525"]},
        )
        self.assertEqual(out, [0])

    def test_humanoid_stand_prefers_humanoid_keeps_quad(self) -> None:
        """T-086: same physique first, other physiques still kept."""
        prep = {
            "donors": [
                {"model": "c3180", "template_id": "m60_49_57_00:c3180_9000"},
                {"model": "c4311", "template_id": "m60_42_37_00:c4311_9005"},
            ],
        }
        slot = {"model": "c4311", "walk_route": ""}
        out = filter_prep_donor_indices_for_physique_compat(
            prep,
            [0, 1],
            slot,
            {"quadruped_slot_model_prefixes": ["c3180", "c5525"]},
        )
        self.assertEqual(out, [1, 0])
        out_only_quad = filter_prep_donor_indices_for_physique_compat(
            prep,
            [0],
            slot,
            {"quadruped_slot_model_prefixes": ["c3180", "c5525"]},
        )
        self.assertEqual(out_only_quad, [0])

    def test_script_flyer_slot_skips_physique_soft_prefer(self) -> None:
        """T-088: c4200 flyer slots keep index order; no flying-first sort."""
        prep = {
            "donors": [
                {"model": "c4313", "template_id": "m35_00_00_00:c4313_9003"},
                {"model": "c4200", "template_id": "m60_43_52_00:c4200_9000"},
            ],
        }
        slot = {
            "model": "c4200",
            "chr_activate": 1000000003,
            "collision_part": "h423700",
            "walk_route": "",
        }
        cfg = {
            "flying_slot_model_prefixes": ["c4200"],
            "script_patrol_flyer_model_prefixes": ["c4200"],
        }
        out = filter_prep_donor_indices_for_physique_compat(
            prep, [0, 1], slot, cfg
        )
        self.assertEqual(out, [0, 1])


if __name__ == "__main__":
    unittest.main()
