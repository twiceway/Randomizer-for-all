"""T-093 slider lift + limgrave map_mult=1."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import (  # noqa: E402
    compute_assignment_patch,
    load_difficulty_cfg,
    resolve_t093_target_effective_hp,
)
from enemy_world_progression import (  # noqa: E402
    compute_slider_lift_mult,
    resolve_map_mult_t093,
    resolve_map_tier_t093,
)


class TestT093SliderLift(unittest.TestCase):
    def test_s_one_unchanged(self) -> None:
        self.assertEqual(compute_slider_lift_mult(1000, 1.0, h_ref=2500, alpha=0.5), 1.0)

    def test_s_gt_one_low_hp_gains_more(self) -> None:
        lo = compute_slider_lift_mult(800, 2.0, h_ref=2500, alpha=0.5)
        hi = compute_slider_lift_mult(8000, 2.0, h_ref=2500, alpha=0.5)
        self.assertGreater(lo, hi)
        self.assertGreater(lo, 1.0)
        self.assertGreater(hi, 1.0)

    def test_s_gt_one_high_hp_at_least_linear(self) -> None:
        """s>1：高血至少按滑条线性（2.0 → ≥2）；低血仍可更高。"""
        hi = compute_slider_lift_mult(70000, 2.0, h_ref=2500, alpha=0.5)
        lo = compute_slider_lift_mult(500, 2.0, h_ref=2500, alpha=0.5)
        self.assertAlmostEqual(hi, 2.0, places=9)
        self.assertGreater(lo, 2.0)
        hi3 = compute_slider_lift_mult(70000, 3.0, h_ref=2500, alpha=0.5)
        self.assertAlmostEqual(hi3, 3.0, places=9)

    def test_s_lt_one_high_hp_drops_more(self) -> None:
        lo = compute_slider_lift_mult(800, 0.5, h_ref=2500, alpha=0.5)
        hi = compute_slider_lift_mult(8000, 0.5, h_ref=2500, alpha=0.5)
        # higher multiplier means less drop; low HP should keep higher ratio
        self.assertGreater(lo, hi)
        self.assertLess(lo, 1.0)
        self.assertLess(hi, 1.0)

    def test_limgrave_map_mult_is_one(self) -> None:
        from enemy_world_progression import load_map_regions

        load_map_regions.cache_clear()
        self.assertEqual(resolve_map_tier_t093("m60_42_36_00"), 1)
        self.assertAlmostEqual(resolve_map_mult_t093("m60_42_36_00"), 1.0)

    def test_c3060_limgrave_slider1_near_whitelist(self) -> None:
        from enemy_whitelist_hp import (
            load_whitelist_effective_hp_index,
            whitelist_effective_hp_for_model,
        )
        from enemy_world_progression import load_map_regions

        load_map_regions.cache_clear()
        load_whitelist_effective_hp_index.cache_clear()
        cfg = load_difficulty_cfg()
        self.assertTrue(cfg.get("t093_progression", {}).get("enabled"))
        row = {
            "map_id": "m60_42_36_00",
            "model": "c3060",
            "npc": 30600000,
            "tgt_cat": "trash",
            "src_cat": "trash",
        }
        donor = {
            "ID": "30600000",
            "hp": "705",
            "defFlickPower": "30",
            "spEffectID0": "7010",
            "spEffectID1": "0",
            "spEffectID2": "0",
        }
        wl = whitelist_effective_hp_for_model("c3060")
        self.assertIsNotNone(wl)
        assert wl is not None
        self.assertEqual(wl, 3107)
        target = resolve_t093_target_effective_hp(
            row,
            donor,
            difficulty={"enabled": True, "user_mult": 1.0},
            npc_by_id={30600000: donor},
            difficulty_cfg=cfg,
        )
        # must be whitelist scale, not ×3.34 (~2350 from 705)
        self.assertLess(abs(target - wl) / max(wl, 1), 0.05)
        self.assertLess(target, 5000)

        patch = compute_assignment_patch(
            row,
            donor,
            soul_out=100,
            difficulty={"enabled": True, "user_mult": 1.0},
            npc_by_id={30600000: donor},
            difficulty_cfg=cfg,
        )
        self.assertIsNotNone(patch)
        assert patch is not None
        self.assertIn("hp", patch)
        # J1 region SP cleared — table hp ≈ effective
        self.assertLess(abs(int(patch["hp"]) - wl) / max(wl, 1), 0.08)


if __name__ == "__main__":
    unittest.main()
