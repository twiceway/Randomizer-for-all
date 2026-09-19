"""spawn deploy verification."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enemy_spawn_bundle import verify_spawn_deployed


class SpawnDeployVerifyTests(unittest.TestCase):
    def test_verify_spawn_deployed_accepts_matching_files(self) -> None:
        body = "seed=42\nslots=3\n# map_id\nm10_00_00_00\tx\t"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src.txt"
            dest = root / "dest.txt"
            src.write_text(body, encoding="utf-8")
            dest.write_text(body, encoding="utf-8")
            verify_spawn_deployed(src, dest)

    def test_verify_spawn_deployed_rejects_slot_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src.txt"
            dest = root / "dest.txt"
            src.write_text("seed=42\nslots=3\n", encoding="utf-8")
            dest.write_text("seed=42\nslots=99\n", encoding="utf-8")
            with self.assertRaises(OSError):
                verify_spawn_deployed(src, dest)


if __name__ == "__main__":
    unittest.main()
