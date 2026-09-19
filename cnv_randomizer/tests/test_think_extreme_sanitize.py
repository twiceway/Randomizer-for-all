"""T-059: extreme donor think sense must clamp even when lift==0."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_think_difficulty import compute_think_extreme_sanitize_overrides  # noqa: E402
from npc_think_copies import plan_think_copies  # noqa: E402


class ExtremeSanitizeClampTests(unittest.TestCase):
    def test_inquisitor_53111000_clamped(self) -> None:
        patch = compute_think_extreme_sanitize_overrides(
            53111000,
            map_id="m60_42_37_00",
        )
        self.assertIsNotNone(patch)
        assert patch is not None
        ov = patch["field_overrides"]
        self.assertEqual(int(ov["eye_dist"]), 20)
        self.assertEqual(int(float(ov["nose_dist"])), 8)
        self.assertLessEqual(float(ov["SightTargetForgetTime"]), 12.0)
        self.assertLessEqual(int(ov["maxBackhomeDist"]), 45)

    def test_sane_soldier_no_extreme_patch(self) -> None:
        # eye=15 within cap; may still be "extreme" via backhome=85
        patch = compute_think_extreme_sanitize_overrides(
            30200000,
            map_id="m60_42_37_00",
        )
        if patch is None:
            return
        ov = patch["field_overrides"]
        self.assertNotIn("eye_dist", ov)
        self.assertIn("maxBackhomeDist", ov)

    def test_plan_think_copies_creates_row_when_lift_zero(self) -> None:
        rows = [
            {
                "map_id": "m60_42_37_00",
                "tgt_cat": "elite",
                "think": 53111000,
                "npc_donor": 53111089,
                "npc": 880008319,
                "_adaptive_lift": 0.0,
            }
        ]
        copies = plan_think_copies(rows)
        self.assertGreaterEqual(len(copies), 1)
        self.assertTrue(str(rows[0]["think"]).startswith("890"))
        ov = copies[0]["field_overrides"]
        self.assertEqual(int(ov["eye_dist"]), 20)

    def test_fingerprint_includes_slot_tier(self) -> None:
        from enemy_think_difficulty import think_patch_fingerprint

        a = think_patch_fingerprint(
            53111000, {"slot_tier": 1, "field_overrides": {"eye_dist": "20"}}
        )
        b = think_patch_fingerprint(
            53111000, {"slot_tier": 9, "field_overrides": {"eye_dist": "20"}}
        )
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
