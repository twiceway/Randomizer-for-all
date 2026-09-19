"""T-084 R2 — symmetric adaptive lift (r>1 weaken)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import compute_adaptive_lift  # noqa: E402

ALPHA = 0.70
CAP = 1.15


def _lift(donor: int, anchor: int) -> float:
    return compute_adaptive_lift(
        donor,
        anchor,
        difficulty_cfg={
            "adaptive_stat_anchor": {
                "enabled": True,
                "adaptive_lift_power": ALPHA,
                "overshoot_cap": CAP,
            }
        },
    )


class TestAdaptiveLiftSymmetric(unittest.TestCase):
    def test_r_half_strengthen(self) -> None:
        lift = _lift(500, 1000)
        expected = 1.0 - (0.5**ALPHA)
        self.assertAlmostEqual(lift, expected, places=4)
        self.assertGreater(lift, 0.0)

    def test_r_one_zero(self) -> None:
        self.assertEqual(_lift(1000, 1000), 0.0)

    def test_r_two_weaken_capped(self) -> None:
        lift = _lift(2000, 1000)
        expected = 1.0 - ((1.0 / CAP) ** ALPHA)
        self.assertAlmostEqual(lift, expected, places=4)
        self.assertGreater(lift, 0.0)

    def test_higher_r_weaker_within_cap(self) -> None:
        lift_lo = _lift(1100, 1000)
        lift_hi = _lift(1140, 1000)
        self.assertGreater(lift_hi, lift_lo)

    def test_overshoot_cap_clamps_r(self) -> None:
        uncapped = _lift(10000, 1000)
        capped = _lift(1150, 1000)
        self.assertAlmostEqual(uncapped, capped, places=4)


if __name__ == "__main__":
    unittest.main()
