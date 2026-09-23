"""Smoke tests for player_run CLI (scripts pack entry)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import player_run


class PlayerRunTests(unittest.TestCase):
    def test_parser_requires_cmd(self) -> None:
        with self.assertRaises(SystemExit):
            player_run.build_parser().parse_args([])

    def test_parser_doctor(self) -> None:
        ns = player_run.build_parser().parse_args(["doctor"])
        self.assertEqual(ns.cmd, "doctor")
        self.assertEqual(ns.lang, "zh")

    def test_parser_lang_en(self) -> None:
        ns = player_run.build_parser().parse_args(["--lang", "en", "install-runtime"])
        self.assertEqual(ns.lang, "en")
        self.assertEqual(ns.cmd, "install-runtime")

    def test_parser_generate_seed(self) -> None:
        ns = player_run.build_parser().parse_args(
            ["generate", "--seed", "42", "--skip-apply"]
        )
        self.assertEqual(ns.seed, 42)
        self.assertTrue(ns.skip_apply)

    def test_python_ok_on_dev(self) -> None:
        ok, msg = player_run._python_ok()
        self.assertTrue(ok, msg)

    def test_cmd_gui_translation_not_shadowed(self) -> None:
        """Regression: param named '_' must not shadow i18n _(zh, en)."""
        ns = player_run.build_parser().parse_args(["gui"])
        with mock.patch("player_run.subprocess.Popen") as popen:
            proc = mock.Mock()
            proc.pid = 1
            proc.poll.return_value = None
            popen.return_value = proc
            with mock.patch("player_run._wait_for_gui_window", return_value=True):
                code = player_run.cmd_gui(ns)
        self.assertEqual(code, 0)
        popen.assert_called_once()

    def test_cmd_doctor_translation_not_shadowed(self) -> None:
        ns = player_run.build_parser().parse_args(["--lang", "en", "doctor"])
        player_run.set_lang("en")
        code = player_run.cmd_doctor(ns)
        self.assertIn(code, (0, 1))

    def test_scripts_pack_bats_exist(self) -> None:
        root = Path(__file__).resolve().parents[1].parent / "packaging" / "scripts_pack"
        import importlib.util

        emit_py = root / "_emit_bats.py"
        spec = importlib.util.spec_from_file_location("emit_bats", emit_py)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        written = {p.name: p for p in mod.emit(root)}

        for name in (
            "0_安装运行环境.bat",
            "1_打开界面.bat",
            "0_InstallRuntime.bat",
            "1_OpenGUI.bat",
        ):
            self.assertIn(name, written)
            self.assertTrue(written[name].is_file(), name)

        zh = written["0_安装运行环境.bat"].read_bytes()
        zh.decode("gbk")
        with self.assertRaises(UnicodeDecodeError):
            zh.decode("utf-8")
        en = written["0_InstallRuntime.bat"].read_bytes()
        en_text = en.decode("ascii")
        self.assertIn("--lang en", en_text)
        en_gui = written["1_OpenGUI.bat"].read_bytes().decode("ascii")
        self.assertIn("--lang en", en_gui)

        self.assertFalse((root / "1_安装模组到游戏.bat").is_file())
        self.assertFalse((root / "2_生成随机.bat").is_file())


if __name__ == "__main__":
    unittest.main()
