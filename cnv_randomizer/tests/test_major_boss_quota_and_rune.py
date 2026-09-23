"""T-069 图内配额 + 6 池卢恩原血同比（2026-09-23）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enemy_night_spatial_quota import (  # noqa: E402
    NightSpatialQuotaConfig,
    is_major_boss_spatial_quota_exempt,
    major_boss_spatial_cell_key,
    night_cell_at_capacity,
    record_night_cell_use,
)
import enemy_difficulty as ed  # noqa: E402


class TestMajorBossQuotaAndRune(unittest.TestCase):
    def test_major_boss_cell_key_is_map_scoped_not_ow(self):
        cfg = NightSpatialQuotaConfig(
            enabled=True, cell_xz=50.0, cell_y=10.0, max_per_cell=1
        )
        slot = {"pos_x": 125.0, "pos_y": 25.0, "pos_z": 75.0}
        key = major_boss_spatial_cell_key("m60_47_40_00", slot, cfg)
        self.assertEqual(key, ("m60_47_40_00", 2, 2, 1))
        self.assertNotEqual(key[0], "ow")

    def test_major_boss_quota_capacity_one_per_cell(self):
        cfg = NightSpatialQuotaConfig(
            enabled=True, cell_xz=50.0, cell_y=10.0, max_per_cell=1
        )
        used: dict = {}
        key = ("m60_47_40_00", 0, 0, 0)
        self.assertFalse(night_cell_at_capacity(key, used, cfg))
        record_night_cell_use(key, used)
        self.assertTrue(night_cell_at_capacity(key, used, cfg))

    def test_major_boss_quota_exempt_indoor_9000(self):
        slot = {"map_id": "m31_02_00_00", "name": "c3510_9000", "model": "c3510"}
        with patch(
            "boss_npc_detect.is_indoor_dungeon_boss_arena_slot",
            return_value=True,
        ), patch(
            "enemy_category_rules.is_scripted_dungeon_main_boss_slot",
            return_value=False,
        ):
            self.assertTrue(is_major_boss_spatial_quota_exempt(slot, {}))

    def test_scale_rune_major_boss_proportional_to_hp(self):
        row = {"tgt_cat": "major_boss", "map_id": "m60_47_40_00"}
        with patch.object(
            ed,
            "compute_row_adaptive_lift",
            return_value={"donor_eff_hp": 10000, "lift": 0.5},
        ), patch.object(
            ed, "assignment_final_effective_hp", return_value=2500
        ), patch.object(ed, "load_difficulty_cfg", return_value={}):
            out = ed.scale_rune_by_assignment_hp(
                70000,
                row,
                {"hp": "10000"},
                difficulty={"enabled": True},
                npc_by_id={},
                difficulty_cfg={},
            )
        self.assertEqual(out, 17500)

    def test_scale_rune_major_boss_full_hp_keeps_full_runes(self):
        row = {"tgt_cat": "major_boss", "map_id": "m10_00_00_00"}
        with patch.object(
            ed,
            "compute_row_adaptive_lift",
            return_value={"donor_eff_hp": 50000, "lift": 0.0},
        ), patch.object(
            ed, "assignment_final_effective_hp", return_value=50000
        ), patch.object(ed, "load_difficulty_cfg", return_value={}):
            out = ed.scale_rune_by_assignment_hp(
                70000,
                row,
                {},
                difficulty={"enabled": True},
                npc_by_id={},
                difficulty_cfg={},
            )
        self.assertEqual(out, 70000)


if __name__ == "__main__":
    unittest.main()
