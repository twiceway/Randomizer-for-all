"""T-099 D: slider and map lifts multiply from pre-slider HP (no mutual feed)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import load_difficulty_cfg, resolve_t093_target_effective_hp  # noqa: E402
from enemy_whitelist_hp import whitelist_effective_hp_for_model  # noqa: E402


class TestT099LiftSplitMultiply(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = load_difficulty_cfg()
        cls.map_dlc = "m61_48_38_00"  # tier 25
        cls.donor = {"ID": "47300040", "hp": "1", "Name": "Radahn"}

    def _hp(self, model: str, npc: int, user_mult: float) -> int:
        row = {
            "map_id": self.map_dlc,
            "model": model,
            "npc": npc,
            "src_cat": "major_boss",
            "tgt_cat": "major_boss",
        }
        return resolve_t093_target_effective_hp(
            row,
            self.donor,
            difficulty={"user_mult": user_mult, "journey": 1, "enabled": True},
            npc_by_id={},
            difficulty_cfg=self.cfg,
        )

    def test_radahn_slider_monotonic_on_tier25(self) -> None:
        wl = whitelist_effective_hp_for_model("c4730")
        self.assertIsNotNone(wl)
        self.assertGreater(int(wl or 0), 10000)
        h025 = self._hp("c4730", 47300040, 0.25)
        h05 = self._hp("c4730", 47300040, 0.5)
        h10 = self._hp("c4730", 47300040, 1.0)
        self.assertLess(h025, h05, f"0.25={h025} should be < 0.5={h05}")
        self.assertLess(h05, h10, f"0.5={h05} should be < 1.0={h10}")
        # No map-layer blow-up after crush
        self.assertLess(h025, 5000)

    def test_morgott_no_astronomical_at_025(self) -> None:
        h = self._hp("c4760", 47600000, 0.25)
        self.assertLess(h, 500_000, f"morgott 0.25 blew up: {h}")
        self.assertGreater(h, 1)

    def test_user_mult_1_unchanged_shape(self) -> None:
        """At s=1, map_eff uses full base → final ≈ base * map_nom for high-HP."""
        h = self._hp("c4730", 47300040, 1.0)
        wl = int(whitelist_effective_hp_for_model("c4730") or 0)
        # tier25 map_nom 1.5 → ~31176
        self.assertGreater(h, int(wl * 1.4))
        self.assertLess(h, int(wl * 1.6) + 50)

    def test_morgott_doubles_at_slider_2(self) -> None:
        h1 = self._hp("c4760", 47600000, 1.0)
        h2 = self._hp("c4760", 47600000, 2.0)
        self.assertGreaterEqual(h2, int(h1 * 2 * 0.99))
        self.assertLessEqual(h2, int(h1 * 2 * 1.01) + 5)


if __name__ == "__main__":
    unittest.main()
