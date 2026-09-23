"""人型红灵：原皮表血×滑条 + Human-NPC 区域/周目重绑。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import (  # noqa: E402
    is_human_npc_hp_model,
    is_ng_region_sp,
    rebind_region_sp_effects,
    resolve_human_npc_area_ng_sp,
    resolve_human_npc_table_hp,
)


class TestHumanNpcHpScale(unittest.TestCase):
    def test_model_gate(self) -> None:
        self.assertTrue(is_human_npc_hp_model("c0000"))
        self.assertTrue(is_human_npc_hp_model("c0000_9001"))
        self.assertFalse(is_human_npc_hp_model("c3100"))
        self.assertFalse(is_human_npc_hp_model("c2010"))

    def test_abyss_area_ng(self) -> None:
        area, ng = resolve_human_npc_area_ng_sp("m61_47_40_00")
        self.assertEqual(area, 20007300)
        self.assertEqual(ng, 20007700)

    def test_limgrave_area_ng(self) -> None:
        area, ng = resolve_human_npc_area_ng_sp("m60_42_36_00")
        self.assertEqual(area, 19351)
        self.assertEqual(ng, 19501)

    def test_table_hp_slider(self) -> None:
        donor = {"hp": "1551"}
        self.assertEqual(resolve_human_npc_table_hp(donor, {"user_mult": 0.5}), 776)
        self.assertEqual(resolve_human_npc_table_hp(donor, {"user_mult": 1.0}), 1551)

    def test_rebind_human_keeps_area_not_monster_ng(self) -> None:
        donor = {
            "hp": "1551",
            "spEffectID0": "5400",
            "spEffectID3": "19359",
            "GameClearSpEffectID": "19510",
        }
        ov = rebind_region_sp_effects(
            donor, 25, map_id="m61_47_40_00", model="c0000"
        )
        self.assertEqual(ov.get("spEffectID3"), "20007300")
        self.assertEqual(ov.get("GameClearSpEffectID"), "20007700")
        # no monster 74xx NG inject
        for v in ov.values():
            if v in ("0", "", None):
                continue
            self.assertFalse(is_ng_region_sp(v), ov)

    def test_monster_path_still_clears_dlc_pack(self) -> None:
        donor = {
            "hp": "538",
            "spEffectID3": "20007030",
            "GameClearSpEffectID": "20007430",
        }
        ov = rebind_region_sp_effects(donor, 1, map_id="m60_42_36_00", model="c4100")
        self.assertEqual(ov.get("GameClearSpEffectID"), "0")
        # DLC pack cleared; intentional monster NG 74xx written somewhere
        self.assertTrue(any(is_ng_region_sp(v) for v in ov.values() if v not in ("0", "")), ov)
        self.assertNotIn("20007030", set(ov.values()))
        self.assertNotIn("20007430", set(ov.values()))


if __name__ == "__main__":
    unittest.main()
