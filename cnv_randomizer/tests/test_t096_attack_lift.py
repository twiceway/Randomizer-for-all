"""T-096 attack map-only lift + mod attack sp (journey stays engine)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import (  # noqa: E402
    _attack_sp_rate_table,
    _pick_attack_sp_for_rate,
    compute_assignment_patch,
    compute_t093_attack_lift_mult,
    load_difficulty_cfg,
    resolve_adaptive_attack_sp,
)
from enemy_world_progression import (  # noqa: E402
    load_region_progression,
    nominal_journey_atk_mult,
    nominal_map_atk_mult,
    resolve_bracket_cap_mult,
)


class TestT096AttackLift(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_region_progression.cache_clear()
        cls.cfg = load_difficulty_cfg()
        cls.abyss = "m61_46_38_00"

    def _row(self, model: str, npc: int, *, cat: str = "trash") -> dict:
        return {
            "map_id": self.abyss,
            "model": model,
            "npc": npc,
            "tgt_cat": cat,
            "src_cat": cat,
        }

    def _donor(self, npc: int, hp: str = "200") -> dict:
        return {
            "ID": str(npc),
            "hp": hp,
            "defFlickPower": "40",
            "spEffectID0": "0",
            "spEffectID1": "0",
            "spEffectID2": "0",
            "spEffectID3": "0",
            "spEffectID4": "0",
        }

    def test_nominal_map_atk_max(self) -> None:
        self.assertAlmostEqual(
            nominal_map_atk_mult(25, difficulty_cfg=self.cfg), 1.5, places=5
        )
        self.assertAlmostEqual(
            nominal_map_atk_mult(1, difficulty_cfg=self.cfg), 1.0, places=5
        )

    def test_attack_bracket_cap(self) -> None:
        self.assertAlmostEqual(
            resolve_bracket_cap_mult(605, kind="attack", difficulty_cfg=self.cfg),
            6.0,
            places=5,
        )
        self.assertAlmostEqual(
            resolve_bracket_cap_mult(3896, kind="attack", difficulty_cfg=self.cfg),
            1.0,
            places=5,
        )
        self.assertAlmostEqual(
            resolve_bracket_cap_mult(8000, kind="attack", difficulty_cfg=self.cfg),
            1.1,
            places=5,
        )

    def test_c2041_abyss_map_attack_near_six(self) -> None:
        npc = 20410050
        donor = self._donor(npc)
        row = self._row("c2041", npc)
        diff = {"enabled": True, "user_mult": 1.0, "journey_tier": 1}
        map_atk = compute_t093_attack_lift_mult(
            row,
            donor,
            difficulty=diff,
            npc_by_id={npc: donor},
            difficulty_cfg=self.cfg,
        )
        self.assertAlmostEqual(map_atk, 6.0, places=2)

    def test_map_attack_unchanged_by_journey(self) -> None:
        npc = 20410050
        donor = self._donor(npc)
        row = self._row("c2041", npc)
        diff_j1 = {"enabled": True, "user_mult": 1.0, "journey_tier": 1}
        diff_j9 = {"enabled": True, "user_mult": 1.0, "journey_tier": 9}
        map_j1 = compute_t093_attack_lift_mult(
            row, donor, difficulty=diff_j1, npc_by_id={npc: donor}, difficulty_cfg=self.cfg
        )
        map_j9 = compute_t093_attack_lift_mult(
            row, donor, difficulty=diff_j9, npc_by_id={npc: donor}, difficulty_cfg=self.cfg
        )
        self.assertAlmostEqual(map_j1, map_j9, places=5)
        atk_j1 = resolve_adaptive_attack_sp(
            donor,
            row=row,
            lift=0.0,
            occupied_slots={},
            difficulty_cfg=self.cfg,
            difficulty=diff_j1,
            npc_by_id={npc: donor},
        )
        atk_j9 = resolve_adaptive_attack_sp(
            donor,
            row=row,
            lift=0.0,
            occupied_slots={},
            difficulty_cfg=self.cfg,
            difficulty=diff_j9,
            npc_by_id={npc: donor},
        )
        self.assertIsNotNone(atk_j1)
        self.assertIsNotNone(atk_j9)
        self.assertEqual(atk_j1[1], atk_j9[1])
        table = _attack_sp_rate_table(self.cfg)
        mod = table[int(atk_j1[1])]
        eng_j9 = nominal_journey_atk_mult(9, difficulty_cfg=self.cfg)
        self.assertAlmostEqual(eng_j9, 1.45, places=2)
        self.assertGreaterEqual(mod, 4.6)
        self.assertAlmostEqual(mod * eng_j9, 6.73, delta=0.05)

    def test_reference_trash_no_attack_sp(self) -> None:
        npc = 57400000
        donor = self._donor(npc, hp="3500")
        row = self._row("c5740", npc)
        diff = {"enabled": True, "user_mult": 1.0, "journey_tier": 9}
        map_atk = compute_t093_attack_lift_mult(
            row, donor, difficulty=diff, npc_by_id={npc: donor}, difficulty_cfg=self.cfg
        )
        self.assertAlmostEqual(map_atk, 1.0, places=2)
        self.assertIsNone(
            resolve_adaptive_attack_sp(
                donor,
                row=row,
                lift=0.0,
                occupied_slots={},
                difficulty_cfg=self.cfg,
                difficulty=diff,
                npc_by_id={npc: donor},
            )
        )

    def test_strong_monster_modest_map_attack(self) -> None:
        npc = 47600014
        donor = self._donor(npc, hp="8000")
        row = self._row("c4760", npc)
        diff = {"enabled": True, "user_mult": 1.0, "journey_tier": 9}
        map_atk = compute_t093_attack_lift_mult(
            row, donor, difficulty=diff, npc_by_id={npc: donor}, difficulty_cfg=self.cfg
        )
        self.assertAlmostEqual(map_atk, 1.1, places=2)

    def test_major_boss_skips_attack_sp(self) -> None:
        npc = 47500014
        donor = self._donor(npc, hp="5500")
        row = self._row("c4750", npc, cat="major_boss")
        diff = {"enabled": True, "user_mult": 1.0, "journey_tier": 9}
        self.assertIsNone(
            resolve_adaptive_attack_sp(
                donor,
                row=row,
                lift=0.5,
                occupied_slots={},
                difficulty_cfg=self.cfg,
                difficulty=diff,
                npc_by_id={npc: donor},
            )
        )

    def test_pick_sp_for_high_map_rate(self) -> None:
        picked = _pick_attack_sp_for_rate(5.8, self.cfg)
        self.assertIsNotNone(picked)
        sp_id, rate = picked
        self.assertEqual(sp_id, 20007131)
        self.assertGreaterEqual(rate, 4.6)

    def test_patch_includes_attack_mult(self) -> None:
        npc = 20410050
        donor = self._donor(npc)
        row = self._row("c2041", npc)
        diff = {"enabled": True, "user_mult": 1.0, "journey_tier": 1}
        patch = compute_assignment_patch(
            row,
            donor,
            soul_out=100,
            difficulty=diff,
            npc_by_id={npc: donor},
            difficulty_cfg=self.cfg,
        )
        self.assertIsNotNone(patch)
        self.assertIn("t093_attack_mult", patch)
        self.assertGreater(float(patch["t093_attack_mult"]), 1.0)
        self.assertIn("attack_sp", patch)


if __name__ == "__main__":
    unittest.main()
