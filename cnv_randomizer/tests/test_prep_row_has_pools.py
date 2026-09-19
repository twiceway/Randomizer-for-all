"""prep_row_has_pools — empty o:{} must not count as cached pools."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_slot_prep import prep_row_has_pools  # noqa: E402


class PrepRowHasPoolsTests(unittest.TestCase):
    def test_empty_dict_false(self) -> None:
        self.assertFalse(prep_row_has_pools({"o": {}}))

    def test_nonempty_pool_true(self) -> None:
        self.assertTrue(prep_row_has_pools({"o": {"trash": [1, 2]}}))

    def test_missing_o_false(self) -> None:
        self.assertFalse(prep_row_has_pools({}))


if __name__ == "__main__":
    unittest.main()
