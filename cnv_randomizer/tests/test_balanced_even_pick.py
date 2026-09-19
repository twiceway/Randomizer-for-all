"""T-098: main-table even pick; no auto structural tail."""

from __future__ import annotations

import random
import sys
import unittest
from collections import Counter
from math import ceil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_donor_pick import (  # noqa: E402
    _pick_balanced_npc_for_slot,
    identify_structural_tail_npcs,
)


class TestBalancedEvenPick(unittest.TestCase):
    def test_no_auto_tail_by_cap(self) -> None:
        npc_slot_cap = {1: 127, 2: 90, 3: 50}
        categories_cfg = {
            "pool_npc_structural_tail_ratio": 0.2,
            "pool_npc_structural_tail_min_slots": 5,
            "pool_npc_structural_tail_max_cap_ratio": 0.78,
            "pool_npc_structural_tail_npcs": {},
        }
        tail = identify_structural_tail_npcs(
            npc_slot_cap, categories_cfg, "major_boss"
        )
        self.assertEqual(tail, set())

    def test_manual_tail_still_forces(self) -> None:
        categories_cfg = {
            "pool_npc_structural_tail_npcs": {"major_boss": {"2": True}},
        }
        tail = identify_structural_tail_npcs(
            {1: 10, 2: 10}, categories_cfg, "major_boss"
        )
        self.assertEqual(tail, {2})

    def test_ab_toy_even_not_b_zero(self) -> None:
        """A slots 1-10, B slots 1-5; scarce-first + least-count -> ~5/5."""
        a, b = "A", "B"
        # 10 plans: first 5 only A; next 5 A+B. Process scarce (only A) first.
        plans: list[dict] = []
        for i in range(5):
            plans.append({a: [0]})
        for i in range(5):
            plans.append({a: [0], b: [1]})
        plans.sort(key=lambda d: (len(d), random.Random(0).randint(0, 99)))
        # Force scarce-first order explicitly
        plans = [{a: [0]} for _ in range(5)] + [{a: [0], b: [1]} for _ in range(5)]

        npc_slot_cap = {a: 10, b: 5}
        soft_cap = max(1, ceil(10 / 2))
        rng = random.Random(42)
        counts: Counter = Counter()
        structural_tail: set = set()
        weights = {a: 1.0, b: 1.0}
        for by_npc in plans:
            npc = _pick_balanced_npc_for_slot(
                by_npc,
                counts,
                npc_slot_cap,
                weights,
                soft_cap,
                rng,
                structural_tail=structural_tail,
            )
            self.assertIsNotNone(npc)
            counts[npc] += 1
        self.assertGreater(counts[b], 0)
        self.assertEqual(counts[a], 5)
        self.assertEqual(counts[b], 5)

    def test_manual_cold_skipped_when_main_present(self) -> None:
        a, cold = "A", "C"
        by_npc = {a: [0], cold: [1]}
        counts: Counter = Counter()
        npc_slot_cap = {a: 10, cold: 10}
        rng = random.Random(1)
        for _ in range(5):
            npc = _pick_balanced_npc_for_slot(
                by_npc,
                counts,
                npc_slot_cap,
                {a: 1.0, cold: 8.0},
                soft_cap=5,
                rng=rng,
                structural_tail={cold},
            )
            self.assertEqual(npc, a)
            counts[npc] += 1
        self.assertEqual(counts[cold], 0)


if __name__ == "__main__":
    unittest.main()
