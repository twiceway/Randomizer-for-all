"""npc_think_sanitize — think 族与 model 对齐（T-083）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from npc_think_sanitize import (  # noqa: E402
    is_runtime_think_copy_id,
    think_matches_model_family,
)


class ThinkModelFamilyTests(unittest.TestCase):
    def test_same_family(self) -> None:
        self.assertTrue(think_matches_model_family("c4315", 43151001))
        self.assertTrue(think_matches_model_family("c5590", 55900000))

    def test_copy_id_exempt(self) -> None:
        self.assertTrue(think_matches_model_family("c0000", 890000011))
        self.assertTrue(is_runtime_think_copy_id(890000011))

    def test_c0000_exempt(self) -> None:
        self.assertTrue(think_matches_model_family("c0000", 543760000))

    def test_cross_family(self) -> None:
        self.assertFalse(think_matches_model_family("c5590", 43151001))
        self.assertFalse(think_matches_model_family("c4315", 55900000))


if __name__ == "__main__":
    unittest.main()
