"""Donor leftover maxHpRate SpEffects must be cleared on copy rebind."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import (  # noqa: E402
    _attack_sp_has_hp_mult,
    _sp_max_hp_rate,
    is_ng_region_sp,
    rebind_region_sp_effects,
)


class TestLeftoverHpSpClear(unittest.TestCase):
    def test_clears_dlc_hp_pack_keeps_ng_region(self) -> None:
        donor = {
            "hp": "538",
            "spEffectID0": "5400",
            "spEffectID1": "12501",
            "spEffectID2": "7060",
            "spEffectID3": "20007030",
            "spEffectID5": "90400",
            "GameClearSpEffectID": "20007430",
        }
        self.assertGreater(_sp_max_hp_rate(20007030), 1.01)
        ov = rebind_region_sp_effects(donor, 1)
        self.assertEqual(ov.get("spEffectID3"), "0")
        self.assertEqual(ov.get("GameClearSpEffectID"), "0")
        self.assertEqual(ov.get("spEffectID2"), "0")  # J1 region cleared
        ng_vals = [v for v in ov.values() if v not in ("0", "")]
        self.assertTrue(any(is_ng_region_sp(v) for v in ng_vals), ov)
        # rate==1 packs not zeroed by leftover cleaner
        self.assertNotEqual(ov.get("spEffectID1"), "0")
        self.assertNotEqual(ov.get("spEffectID5"), "0")

    def test_pure_attack_sp_not_cleared_as_leftover(self) -> None:
        # 8501 is pure attack (maxHpRate==1) in current pool
        self.assertFalse(_attack_sp_has_hp_mult(8501))
        donor = {
            "hp": "400",
            "spEffectID0": "8501",
            "spEffectID1": "20007030",
        }
        ov = rebind_region_sp_effects(donor, 1)
        self.assertEqual(ov.get("spEffectID1"), "0")
        # 8501 must not be forced to 0 by leftover cleaner (may be overwritten if
        # NG inject picks that slot — only assert cleaner did not target it alone)
        merged = dict(donor)
        merged.update(ov)
        # After full rebind, no leftover hp-mult except intentional NG 74xx
        for key, val in merged.items():
            if not (key.startswith("spEffectID") or key == "GameClearSpEffectID"):
                continue
            if val in ("", "0", "-1", None):
                continue
            sid = int(val)
            if is_ng_region_sp(sid):
                continue
            self.assertFalse(
                _attack_sp_has_hp_mult(sid),
                f"{key}={sid} still has maxHpRate≠1 after rebind",
            )

    def test_skeleton_like_effective_no_extra_mult(self) -> None:
        donor = {
            "hp": "538",
            "spEffectID0": "5400",
            "spEffectID1": "12501",
            "spEffectID2": "7410",
            "spEffectID3": "20007030",
            "spEffectID5": "90400",
            "GameClearSpEffectID": "20007430",
        }
        ov = rebind_region_sp_effects(donor, 1)
        merged = dict(donor)
        merged.update(ov)
        extra = 1.0
        ng_count = 0
        for key, val in merged.items():
            if not (key.startswith("spEffectID") or key == "GameClearSpEffectID"):
                continue
            if val in ("", "0", "-1", None):
                continue
            sid = int(val)
            if is_ng_region_sp(sid):
                ng_count += 1
                continue
            rate = _sp_max_hp_rate(sid)
            if abs(rate - 1.0) > 1e-6:
                extra *= rate
        self.assertEqual(ng_count, 1, merged)
        self.assertAlmostEqual(extra, 1.0, places=5)


if __name__ == "__main__":
    unittest.main()
