"""生产配置须把 c3180 狼列入四足前缀（T-076 案例 C）。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from enemy_randomizer_core import donor_physique_bucket, quadruped_model_prefixes

_CATEGORIES = json.loads(
    (Path(__file__).resolve().parents[1] / "enemy_categories.json").read_text(
        encoding="utf-8-sig"
    )
)


class QuadrupedConfigTests(unittest.TestCase):
    def test_c3180_in_production_quadruped_prefixes(self) -> None:
        prefixes = quadruped_model_prefixes(_CATEGORIES)
        self.assertIn("c3180", prefixes)

    def test_c3180_donor_bucket_is_quadruped(self) -> None:
        tpl = {"model": "c3180", "template_id": "m60_49_57_00:c3180_9000"}
        self.assertEqual(donor_physique_bucket(tpl, _CATEGORIES), "quadruped")


if __name__ == "__main__":
    unittest.main()
