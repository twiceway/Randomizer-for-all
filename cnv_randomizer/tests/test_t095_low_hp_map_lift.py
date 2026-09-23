"""T-095 low-HP map layer lift + bracket caps."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import (  # noqa: E402
    compute_t093_stat_lift_mult,
    load_difficulty_cfg,
    resolve_t093_target_effective_hp,
)
from enemy_world_progression import (  # noqa: E402
    load_region_progression,
    map_layer_lift_mult,
    resolve_bracket_cap_mult,
)


class TestT095LowHpMapLift(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_region_progression.cache_clear()
        cls.cfg = load_difficulty_cfg()
        cls.abyss = "m61_46_38_00"

    def _hp(
        self,
        model: str,
        npc: int,
        *,
        journey: int = 1,
        hp_stub: str = "1000",
    ) -> int:
        donor = {
            "ID": str(npc),
            "hp": hp_stub,
            "defFlickPower": "40",
            "spEffectID0": "0",
        }
        row = {
            "map_id": self.abyss,
            "model": model,
            "npc": npc,
            "tgt_cat": "trash",
            "src_cat": "trash",
        }
        return resolve_t093_target_effective_hp(
            row,
            donor,
            difficulty={
                "enabled": True,
                "user_mult": 1.0,
                "journey_tier": journey,
            },
            npc_by_id={npc: donor},
            difficulty_cfg=self.cfg,
        )

    def test_bracket_cap_weak_vs_strong(self) -> None:
        self.assertAlmostEqual(
            resolve_bracket_cap_mult(605, kind="hp", difficulty_cfg=self.cfg), 7.0
        )
        self.assertAlmostEqual(
            resolve_bracket_cap_mult(71454, kind="hp", difficulty_cfg=self.cfg), 3.0
        )

    def test_map_layer_stronger_than_journey_for_low_hp(self) -> None:
        weak = map_layer_lift_mult(605, 1.5, difficulty_cfg=self.cfg)
        same_journey = map_layer_lift_mult(605, 1.5, difficulty_cfg=self.cfg)
        # map uses dedicated alpha; should exceed old layer at 605
        from enemy_world_progression import asymmetric_layer_lift_mult

        old = asymmetric_layer_lift_mult(605, 1.5, h_ref=2500, alpha=0.5)
        self.assertGreater(weak, old)
        self.assertGreaterEqual(weak, 1.5)
        self.assertEqual(weak, same_journey)

    def test_c2041_abyss_j1_near_vanilla_trash(self) -> None:
        hp = self._hp("c2041", 20410050, journey=1, hp_stub="605")
        self.assertGreaterEqual(hp, 3800)
        self.assertLessEqual(hp, 4100)

    def test_c2041_abyss_j9_not_flat_triple(self) -> None:
        hp = self._hp("c2041", 20410050, journey=9, hp_stub="605")
        self.assertGreaterEqual(hp, 3500)
        self.assertGreater(hp, 605 * 3)

    def test_c4760_abyss_j9_near_triple_not_required_exact(self) -> None:
        hp = self._hp("c4760", 47601050, journey=9, hp_stub="71454")
        ratio = hp / 71454
        self.assertGreaterEqual(ratio, 0.85 * 3.0)
        self.assertLessEqual(ratio, 3.0 + 0.01)

    def test_c3805_abyss_j9_within_cap(self) -> None:
        hp = self._hp("c3805", 38050050, journey=9, hp_stub="5010")
        self.assertLessEqual(hp, int(5010 * 3.0) + 5)
        self.assertGreaterEqual(hp, int(5010 * 2.5))

    def test_weak_stat_cap_above_two(self) -> None:
        donor = {
            "ID": "20410050",
            "hp": "605",
            "defFlickPower": "40",
            "spEffectID0": "0",
        }
        row = {
            "map_id": self.abyss,
            "model": "c2041",
            "npc": 20410050,
            "tgt_cat": "trash",
            "src_cat": "trash",
        }
        stat = compute_t093_stat_lift_mult(
            row,
            donor,
            difficulty={"enabled": True, "user_mult": 1.0, "journey_tier": 9},
            npc_by_id={20410050: donor},
            difficulty_cfg=self.cfg,
        )
        self.assertGreater(stat, 2.0)
        # T-099：地图层对层前血分算，弱怪 J9+深渊可略高于旧「帽×2」观感上限 4
        self.assertLessEqual(stat, 4.5 + 0.01)


if __name__ == "__main__":
    unittest.main()
