"""Smoke runner without pytest."""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mod_install as mi

MIN_ME3 = """# test me3
[[package]]
id = "convergence-er"
path = "./../mod"
load_after = []
"""


def main() -> None:
    once = mi._insert_me3_blocks(MIN_ME3)
    assert mi._me3_has_package(once) and mi._me3_has_natives(once)
    twice = mi._insert_me3_blocks(once)
    assert twice.count('id = "cnv-enemy-poc"') == 1
    cleaned = mi._remove_me3_blocks(once)
    assert not mi._me3_has_package(cleaned)
    assert "cnv_pickup_hook.dll" not in cleaned
    print("me3 ok")

    td = Path(tempfile.mkdtemp())
    try:
        game = td / "Game"
        (game / "me3").mkdir(parents=True)
        (game / "mod" / "map").mkdir(parents=True)
        (game / "eldenring.exe").write_bytes(b"MZ")
        (game / "me3" / "convergence.me3").write_text(MIN_ME3, encoding="utf-8")
        src = td / "src.dll"
        src.write_bytes(b"dllbytes")
        mi._product_version = lambda _p: mi.ER_REQUIRED_PRODUCT  # type: ignore
        mi._process_running = lambda: (False, "")  # type: ignore
        mi.find_dll_source = lambda: src  # type: ignore
        mi.save_game_dir = lambda _p: td / "game_path.json"  # type: ignore
        r = mi.install_mod(game)
        assert r.ok, r.messages
        assert mi.is_mod_installed(game)
        r2 = mi.install_mod(game)
        assert r2.ok, r2.messages
        text = (game / "me3" / "convergence.me3").read_text(encoding="utf-8")
        assert text.count('id = "cnv-enemy-poc"') == 1
        u = mi.uninstall_mod(game)
        assert u.ok and not mi.is_mod_installed(game)
        print("install ok")
    finally:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    main()
