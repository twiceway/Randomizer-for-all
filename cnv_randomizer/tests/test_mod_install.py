"""Unit tests for mod_install me3 idempotency and install gates (no real Game)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import mod_install as mi  # noqa: E402


MIN_ME3 = """# test me3
[[package]]
id = "convergence-er"
path = "./../mod"
load_after = []
"""


def test_insert_me3_blocks_idempotent():
    once = mi._insert_me3_blocks(MIN_ME3)
    assert mi._me3_has_package(once)
    assert mi._me3_has_natives(once)
    twice = mi._insert_me3_blocks(once)
    assert twice.count('id = "cnv-enemy-poc"') == 1
    assert twice.count("cnv_pickup_hook.dll") == 1


def test_remove_me3_blocks():
    text = mi._insert_me3_blocks(MIN_ME3)
    cleaned = mi._remove_me3_blocks(text)
    assert not mi._me3_has_package(cleaned)
    assert "cnv_pickup_hook.dll" not in cleaned
    assert "convergence-er" in cleaned


def test_is_mod_installed_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    game = tmp_path / "Game"
    (game / "me3").mkdir(parents=True)
    (game / "mod" / "dll").mkdir(parents=True)
    me3 = game / "me3" / "convergence.me3"
    me3.write_text(mi._insert_me3_blocks(MIN_ME3), encoding="utf-8")
    dll = game / "mod" / "dll" / mi.DLL_NAME
    dll.write_bytes(b"fake")
    assert mi.is_mod_installed(game)

    dll.unlink()
    assert not mi.is_mod_installed(game)


def test_install_requires_force_on_bad_er(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    game = tmp_path / "Game"
    (game / "me3").mkdir(parents=True)
    (game / "mod" / "map").mkdir(parents=True)
    (game / "eldenring.exe").write_bytes(b"MZ")
    (game / "me3" / "convergence.me3").write_text(
        MIN_ME3.replace("convergence-er", "convergence-er"),
        encoding="utf-8",
    )
    monkeypatch.setattr(mi, "_product_version", lambda _p: "1.0.0.0")
    monkeypatch.setattr(mi, "_process_running", lambda: (False, ""))
    monkeypatch.setattr(mi, "find_dll_source", lambda: None)

    r = mi.install_mod(game, force=False)
    assert not r.ok
    assert any("强制安装" in m for m in r.messages)


def test_install_dry_run_and_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    game = tmp_path / "Game"
    (game / "me3").mkdir(parents=True)
    (game / "mod" / "map").mkdir(parents=True)
    (game / "eldenring.exe").write_bytes(b"MZ")
    (game / "me3" / "convergence.me3").write_text(MIN_ME3, encoding="utf-8")
    src = tmp_path / "src.dll"
    src.write_bytes(b"dllbytes")

    monkeypatch.setattr(mi, "_product_version", lambda _p: mi.ER_REQUIRED_PRODUCT)
    monkeypatch.setattr(mi, "_process_running", lambda: (False, ""))
    monkeypatch.setattr(mi, "find_dll_source", lambda: src)
    monkeypatch.setattr(mi, "save_game_dir", lambda p: tmp_path / "game_path.json")

    dry = mi.install_mod(game, force=False, dry_run=True)
    assert dry.ok
    assert not (game / "mod" / "dll" / mi.DLL_NAME).exists()

    done = mi.install_mod(game, force=False, dry_run=False)
    assert done.ok
    assert (game / "mod" / "dll" / mi.DLL_NAME).read_bytes() == b"dllbytes"
    assert mi.is_mod_installed(game)

    # idempotent second pass
    again = mi.install_mod(game, force=False, dry_run=False)
    assert again.ok
    text = (game / "me3" / "convergence.me3").read_text(encoding="utf-8")
    assert text.count('id = "cnv-enemy-poc"') == 1

    un = mi.uninstall_mod(game, remove_dll=True)
    assert un.ok
    assert not mi.is_mod_installed(game)


def test_process_blocks_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    game = tmp_path / "Game"
    (game / "me3").mkdir(parents=True)
    (game / "eldenring.exe").write_bytes(b"MZ")
    (game / "me3" / "convergence.me3").write_text(MIN_ME3, encoding="utf-8")
    monkeypatch.setattr(mi, "_product_version", lambda _p: mi.ER_REQUIRED_PRODUCT)
    monkeypatch.setattr(mi, "_process_running", lambda: (True, "正在运行：eldenring.exe"))
    r = mi.install_mod(game, force=True)
    assert not r.ok
    assert "正在运行" in r.messages[0]
