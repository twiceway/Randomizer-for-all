"""Attack_sp must never use SpEffects that also scale HP (maxHpRate≠1)."""

from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from dlc_donor_pool import load_sp_hp_rates  # noqa: E402
from enemy_difficulty import (  # noqa: E402
    _attack_sp_has_hp_mult,
    _attack_sp_rate_table,
    _forbidden_attack_sp_ids,
    _pick_attack_sp_for_rate,
    _region_hp_sp_ids,
    compute_assignment_patch,
    engine_hp_mult_at_ng,
    is_journey1_region_sp,
    is_ng_region_sp,
    load_difficulty_cfg,
)


class TestAttackSpNoRegionHp(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = load_difficulty_cfg()
        cls.hp_rates = load_sp_hp_rates()

    def test_attack_sp_table_excludes_region_hp_ids(self) -> None:
        region = _region_hp_sp_ids(self.cfg)
        table = _attack_sp_rate_table(self.cfg)
        overlap = region & set(table)
        self.assertFalse(overlap, f"region hp ids in attack table: {overlap}")

    def test_attack_sp_table_excludes_any_max_hp_mult(self) -> None:
        table = _attack_sp_rate_table(self.cfg)
        dirty = [sid for sid in table if _attack_sp_has_hp_mult(sid)]
        self.assertEqual(dirty, [], f"attack table has maxHpRate≠1: {dirty}")

    def test_pick_attack_sp_never_hp_mult(self) -> None:
        for required in (1.05, 1.2, 1.5, 2.0, 2.8, 3.5, 4.5, 6.0):
            picked = _pick_attack_sp_for_rate(required, self.cfg)
            if picked is None:
                continue
            sp_id, _ = picked
            self.assertFalse(
                _attack_sp_has_hp_mult(sp_id),
                f"required={required} picked hp-scaling sp {sp_id}",
            )
            self.assertNotIn(sp_id, _forbidden_attack_sp_ids(self.cfg))

    def test_known_dirty_ids_not_pickable(self) -> None:
        table = _attack_sp_rate_table(self.cfg)
        for sid in (20007131, 19565, 7302, 7308, 7060):
            if abs(float(self.hp_rates.get(str(sid), 1.0)) - 1.0) <= 1e-6:
                continue
            self.assertNotIn(sid, table, sid)
            self.assertTrue(_attack_sp_has_hp_mult(sid), sid)
            picked = _pick_attack_sp_for_rate(4.5, self.cfg)
            if picked is not None:
                self.assertNotEqual(picked[0], sid)

    def test_limgrave_trash_patch_no_region_attack_sp(self) -> None:
        row = {
            "map_id": "m60_44_36_00",
            "model": "c4481",
            "npc": 41000032,
            "tgt_cat": "elite",
            "src_cat": "trash",
        }
        donor = {
            "ID": "41000032",
            "hp": "400",
            "defFlickPower": "30",
            "spEffectID0": "0",
            "spEffectID1": "0",
            "spEffectID2": "0",
            "spEffectID3": "0",
            "spEffectID4": "0",
        }
        patch = compute_assignment_patch(
            row,
            donor,
            soul_out=50,
            difficulty={"enabled": True, "user_mult": 0.25, "journey_tier": 1},
            npc_by_id={41000032: donor},
            difficulty_cfg=self.cfg,
        )
        self.assertIsNotNone(patch)
        attack = patch.get("attack_sp") or {}
        attack_id = str(attack.get("id") or "")
        if attack_id not in ("", "0", "-1"):
            self.assertFalse(
                is_journey1_region_sp(attack_id) or is_ng_region_sp(attack_id),
                f"attack_sp used region hp id {attack_id}",
            )
            self.assertFalse(_attack_sp_has_hp_mult(int(attack_id)))
        hp_out = int(patch.get("hp") or 400)
        ng_mult = engine_hp_mult_at_ng(1, 1, difficulty_cfg=self.cfg)
        eff = int(hp_out * ng_mult)
        self.assertLess(eff, 2000, f"limgrave eff_hp too high: {eff}")

    def test_caravan_event_map_stonedigger_no_attack_sp(self) -> None:
        """After region fix: event map is limgrave tier1 → no map attack lift."""
        donor_path = Path(r"V:/games/Elden Ring/Game/csv/NpcParam.csv")
        donor = None
        with donor_path.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("ID") == "43821052":
                    donor = row
                    break
        self.assertIsNotNone(donor)
        row = {
            "map_id": "m60_11_09_02",
            "model": "c4382",
            "npc": 43821052,
            "tgt_cat": "trash",
            "src_cat": "trash",
            "src_npc": 22710010,
        }
        patch = compute_assignment_patch(
            row,
            donor,
            soul_out=96,
            difficulty={"enabled": True, "user_mult": 0.25, "journey_tier": 1},
            npc_by_id={43821052: donor},
            difficulty_cfg=self.cfg,
        )
        self.assertIsNotNone(patch)
        self.assertFalse(patch.get("attack_sp"), patch.get("attack_sp"))
        self.assertEqual(int(patch.get("slot_tier") or 0), 1)


if __name__ == "__main__":
    unittest.main()
