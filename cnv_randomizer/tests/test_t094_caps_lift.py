"""T-094 caps + asymmetric map/journey layer lift."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import load_difficulty_cfg, resolve_t093_target_effective_hp  # noqa: E402
from enemy_world_progression import (  # noqa: E402
    asymmetric_layer_lift_mult,
    load_region_progression,
    nominal_journey_atk_mult,
    nominal_journey_hp_mult,
    nominal_map_hp_mult,
    resolve_map_mult_t093,
    t094_config,
)


class TestT094CapsLift(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_region_progression.cache_clear()
        cls.cfg = load_difficulty_cfg()
        cls.t094 = t094_config(cls.cfg)

    def test_nominal_product_map25_journey9(self) -> None:
        m = nominal_map_hp_mult(25, difficulty_cfg=self.cfg)
        j = nominal_journey_hp_mult(9, difficulty_cfg=self.cfg)
        self.assertAlmostEqual(m, 1.5, places=5)
        self.assertAlmostEqual(j, 2.0, places=5)
        self.assertAlmostEqual(m * j, 3.0, places=5)

    def test_journey_gt_map_at_max(self) -> None:
        self.assertGreater(
            nominal_journey_hp_mult(9, difficulty_cfg=self.cfg),
            nominal_map_hp_mult(25, difficulty_cfg=self.cfg),
        )

    def test_limgrave_map_mult_one(self) -> None:
        self.assertEqual(resolve_map_mult_t093("m60_42_36_00"), 1.0)
        self.assertAlmostEqual(nominal_map_hp_mult(1, difficulty_cfg=self.cfg), 1.0)

    def test_asymmetric_low_hp_ge_nominal(self) -> None:
        nom = 1.5
        lo = asymmetric_layer_lift_mult(600, nom, h_ref=2500, alpha=0.5)
        hi = asymmetric_layer_lift_mult(30000, nom, h_ref=2500, alpha=0.5)
        self.assertGreaterEqual(lo, nom)
        self.assertEqual(hi, nom)
        self.assertGreater(lo, hi)

    def test_attack_map_constant_journey_max(self) -> None:
        self.assertAlmostEqual(
            nominal_journey_atk_mult(9, difficulty_cfg=self.cfg), 1.45, places=5
        )

    def test_hard_cap_and_high_hp_full_budget(self) -> None:
        donor = {
            "ID": "47601050",
            "hp": "7080",
            "defFlickPower": "0",
            "spEffectID0": "0",
        }
        row = {
            "map_id": "m61_46_38_00",  # dlc_abyss tier 25
            "model": "c4760",
            "npc": 47601050,
            "tgt_cat": "trash",
            "src_cat": "trash",
        }
        # force whitelist-like base via npc table stub; resolve uses whitelist by model
        npc_by_id = {47601050: donor}
        hp = resolve_t093_target_effective_hp(
            row,
            donor,
            difficulty={"enabled": True, "user_mult": 1.0, "journey_tier": 9},
            npc_by_id=npc_by_id,
            difficulty_cfg=self.cfg,
        )
        # whitelist fire giant ~71454; cap = 3x
        self.assertLessEqual(hp, int(round(71454 * 3 * 1.01)))
        self.assertGreaterEqual(hp, int(round(71454 * 2.9)))

    def test_low_hp_layer_boost_then_cap(self) -> None:
        donor = {
            "ID": "20410050",
            "hp": "200",
            "defFlickPower": "10",
            "spEffectID0": "0",
        }
        row = {
            "map_id": "m61_46_38_00",
            "model": "c2041",
            "npc": 20410050,
            "tgt_cat": "trash",
            "src_cat": "trash",
        }
        hp = resolve_t093_target_effective_hp(
            row,
            donor,
            difficulty={"enabled": True, "user_mult": 1.0, "journey_tier": 9},
            npc_by_id={20410050: donor},
            difficulty_cfg=self.cfg,
        )
        # c2041 whitelist ~605; T-095 bracket cap ×7; J9 abyss should exceed old ×3 flat cap
        cap = 605 * 7
        self.assertLessEqual(hp, cap + 5)
        self.assertGreaterEqual(hp, 605 * 3)
        self.assertGreaterEqual(hp, 3500)

    def test_night_respects_hp_cap(self) -> None:
        donor = {
            "ID": "30600000",
            "hp": "705",
            "defFlickPower": "30",
            "spEffectID0": "0",
        }
        row = {
            "map_id": "m60_42_36_00",
            "model": "c3060",
            "npc": 30600000,
            "tgt_cat": "night",
            "src_cat": "night",
        }
        hp = resolve_t093_target_effective_hp(
            row,
            donor,
            difficulty={"enabled": True, "user_mult": 1.0, "journey_tier": 1},
            npc_by_id={30600000: donor},
            difficulty_cfg=self.cfg,
        )
        # limgrave night: 3107*1.5=4660.5 < 3*3107, so night applies fully
        self.assertGreater(hp, 3100)
        self.assertLess(hp, 3107 * 3 + 10)


if __name__ == "__main__":
    unittest.main()
