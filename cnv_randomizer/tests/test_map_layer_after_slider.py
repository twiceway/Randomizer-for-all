"""Map HP layer applies after slider (no high-HP tier inversion at s=0.25)."""

from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import (  # noqa: E402
    load_difficulty_cfg,
    resolve_t093_assignment_hp_out,
    resolve_t093_target_effective_hp,
)
from enemy_whitelist_hp import whitelist_effective_hp_for_model  # noqa: E402


class TestMapLayerAfterSlider(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = load_difficulty_cfg()
        cls.npc_by_id: dict[int, dict[str, str]] = {}
        for p in (
            Path(r"V:/games/Elden Ring/Game/csv/NpcParam.csv"),
            SCRIPT_DIR / "output" / "runtime" / "NpcParam.csv",
        ):
            if not p.is_file():
                continue
            with p.open(encoding="utf-8-sig", errors="replace") as f:
                for row in csv.DictReader(f):
                    try:
                        cls.npc_by_id[int(row["ID"])] = row
                    except (TypeError, ValueError):
                        continue
        cls.donor = cls.npc_by_id.get(47500014)
        cls.diff_025 = {"user_mult": 0.25, "journey": 1, "enabled": True}
        cls.diff_1 = {"user_mult": 1.0, "journey": 1, "enabled": True}

    def test_godrick_tier3_ge_tier1_at_slider_025(self) -> None:
        self.assertIsNotNone(self.donor)
        wl = whitelist_effective_hp_for_model("c4750")
        self.assertIsNotNone(wl)
        self.assertGreater(int(wl or 0), 10000)
        row1 = {
            "map_id": "m11_00_00_00",
            "model": "c4750",
            "npc": 47500014,
            "tgt_cat": "major_boss",
            "src_cat": "major_boss",
            "entity_name": "c4470_9001",
        }
        row3 = {
            "map_id": "m43_01_00_00",
            "model": "c4750",
            "npc": 47500014,
            "tgt_cat": "major_boss",
            "src_cat": "major_boss",
            "entity_name": "c5920_9000",
        }
        hp1 = resolve_t093_target_effective_hp(
            row1, self.donor, difficulty=self.diff_025, npc_by_id=self.npc_by_id
        )
        hp3 = resolve_t093_target_effective_hp(
            row3, self.donor, difficulty=self.diff_025, npc_by_id=self.npc_by_id
        )
        self.assertGreaterEqual(hp3, hp1, f"tier3={hp3} tier1={hp1}")

    def test_trash_tier25_gt_tier1_at_slider_025(self) -> None:
        # Demi-Human donor used in 1-pool examples
        donor = self.npc_by_id.get(41000032)
        self.assertIsNotNone(donor)
        row1 = {
            "map_id": "m60_43_39_00",
            "model": "c4100",
            "npc": 41000032,
            "tgt_cat": "trash",
            "src_cat": "trash",
            "entity_name": "c4371_9014",
        }
        row25 = {
            "map_id": "m61_48_38_00",
            "model": "c4100",
            "npc": 41000032,
            "tgt_cat": "trash",
            "src_cat": "trash",
            "entity_name": "c5490_9003",
        }
        hp1 = resolve_t093_assignment_hp_out(
            row1, donor, difficulty=self.diff_025, npc_by_id=self.npc_by_id
        )
        hp25 = resolve_t093_assignment_hp_out(
            row25, donor, difficulty=self.diff_025, npc_by_id=self.npc_by_id
        )
        self.assertGreater(hp25, hp1, f"t25={hp25} t1={hp1}")

    def test_slider_1_higher_tier_not_below(self) -> None:
        self.assertIsNotNone(self.donor)
        row1 = {
            "map_id": "m11_00_00_00",
            "model": "c4750",
            "npc": 47500014,
            "tgt_cat": "major_boss",
            "src_cat": "major_boss",
            "entity_name": "c4470_9001",
        }
        row3 = {
            "map_id": "m43_01_00_00",
            "model": "c4750",
            "npc": 47500014,
            "tgt_cat": "major_boss",
            "src_cat": "major_boss",
            "entity_name": "c5920_9000",
        }
        hp1 = resolve_t093_target_effective_hp(
            row1, self.donor, difficulty=self.diff_1, npc_by_id=self.npc_by_id
        )
        hp3 = resolve_t093_target_effective_hp(
            row3, self.donor, difficulty=self.diff_1, npc_by_id=self.npc_by_id
        )
        self.assertGreaterEqual(hp3, hp1, f"s=1 tier3={hp3} tier1={hp1}")


if __name__ == "__main__":
    unittest.main()
