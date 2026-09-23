"""Difficulty slider floor 0.85 + recommended bands."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import normalize_difficulty_settings  # noqa: E402


class TestDifficultySliderFloor(unittest.TestCase):
    def test_clamp_below_min_to_085(self) -> None:
        out = normalize_difficulty_settings(
            {"difficulty": {"enabled": True, "user_mult": 0.25}}
        )
        self.assertAlmostEqual(float(out["user_mult"]), 0.85, places=5)

    def test_keep_normal_and_hell(self) -> None:
        n = normalize_difficulty_settings(
            {"difficulty": {"enabled": True, "user_mult": 1.0}}
        )
        self.assertAlmostEqual(float(n["user_mult"]), 1.0, places=5)
        h = normalize_difficulty_settings(
            {"difficulty": {"enabled": True, "user_mult": 3.0}}
        )
        self.assertAlmostEqual(float(h["user_mult"]), 3.0, places=5)


if __name__ == "__main__":
    unittest.main()
