#!/usr/bin/env python3
"""Player-facing CLI for the scripts release pack (no PyInstaller GUI exe).

Contract: .ai/docs/发行包契约.md §12 · plans/N网无exe兜底发行计划.md

Does not reimplement shuffle logic — calls existing core / mod_install / enemy apply.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from paths import SCRIPT_DIR, ensure_output_dirs, resolve_game_dir, subprocess_no_window_kwargs

PYTHON_DOWNLOAD = "https://www.python.org/downloads/windows/"
DOTNET_DOWNLOAD = (
    "https://dotnet.microsoft.com/download/dotnet/8.0"
)
WINGET_PYTHON = "Python.Python.3.13"
WINGET_DOTNET = "Microsoft.DotNet.DesktopRuntime.8"
WINGET_DOTNET_SDK = "Microsoft.DotNet.SDK.8"

# zh (default) | en — set by global --lang before subcommand handlers run
_LANG = "zh"


def set_lang(lang: str) -> None:
    global _LANG
    _LANG = "en" if str(lang).lower() == "en" else "zh"


def _(zh: str, en: str) -> str:
    return en if _LANG == "en" else zh


def _print(msg: str) -> None:
    print(msg, flush=True)


def _which_python() -> str | None:
    for name in ("py", "python", "python3"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _python_ok() -> tuple[bool, str]:
    ver = sys.version_info
    if ver.major != 3 or ver.minor < 11:
        return False, _(
            f"需要 Python 3.11+（推荐 3.13），当前 {ver.major}.{ver.minor}.{ver.micro}",
            f"Need Python 3.11+ (3.13 recommended); found {ver.major}.{ver.minor}.{ver.micro}",
        )
    try:
        import tkinter  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, _(
            f"Python 已安装但缺少界面库（tkinter）：{exc}",
            f"Python found but tkinter missing: {exc}",
        )
    return True, f"Python {ver.major}.{ver.minor}.{ver.micro} OK"


def _dotnet_ok() -> tuple[bool, str]:
    dotnet = shutil.which("dotnet")
    if not dotnet:
        shared = (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "dotnet"
            / "shared"
            / "Microsoft.WindowsDesktop.App"
        )
        if shared.is_dir():
            for child in shared.iterdir():
                if child.is_dir() and child.name.startswith("8."):
                    return True, f".NET Desktop Runtime {child.name} OK"
        return False, _(
            "未找到 .NET 8 Desktop Runtime（也没有 dotnet 命令）",
            ".NET 8 Desktop Runtime not found (and no dotnet command)",
        )
    try:
        proc = subprocess.run(
            [dotnet, "--list-runtimes"],
            capture_output=True,
            text=True,
            timeout=30,
            **subprocess_no_window_kwargs(),
        )
    except OSError as exc:
        return False, _(f"无法运行 dotnet：{exc}", f"Cannot run dotnet: {exc}")
    text = (proc.stdout or "") + (proc.stderr or "")
    for line in text.splitlines():
        if "Microsoft.WindowsDesktop.App" in line and " 8." in line:
            return True, f".NET Desktop Runtime OK ({line.strip()})"
        if "Microsoft.NETCore.App" in line and " 8." in line:
            pass
    for line in text.splitlines():
        if " 8." in line and "Microsoft." in line:
            return True, f".NET 8 runtime OK ({line.strip()})"
    return False, _(
        "dotnet 在，但未看到 8.x 运行时。请安装 .NET 8 Desktop Runtime",
        "dotnet found, but no 8.x runtime. Install .NET 8 Desktop Runtime",
    )


def _dotnet_sdk_ok() -> tuple[bool, str]:
    dotnet = shutil.which("dotnet")
    if not dotnet:
        return False, _(
            "未找到 dotnet（需要 .NET 8 SDK 才能编译敌人小工具）",
            "dotnet not found (.NET 8 SDK required to build enemy helpers)",
        )
    try:
        proc = subprocess.run(
            [dotnet, "--list-sdks"],
            capture_output=True,
            text=True,
            timeout=30,
            **subprocess_no_window_kwargs(),
        )
    except OSError as exc:
        return False, _(f"无法运行 dotnet：{exc}", f"Cannot run dotnet: {exc}")
    text = proc.stdout or ""
    for line in text.splitlines():
        if line.strip().startswith("8."):
            return True, f".NET SDK OK ({line.strip()})"
    return False, _(
        "dotnet 在，但未看到 8.x SDK。请安装 .NET 8 SDK（不只是运行时）",
        "dotnet found, but no 8.x SDK. Install .NET 8 SDK (runtime alone is not enough)",
    )


def _ensure_enemy_helper_tools() -> tuple[bool, str]:
    """Build MsbEnemyPoc / NpcSoulPatch from shipped sources if missing."""
    try:
        from enemy_index_pipeline import _ensure_msb_poc_built
        from npc_soul_copies import ensure_npc_soul_patch_built

        msb = _ensure_msb_poc_built()
        npc = ensure_npc_soul_patch_built()
        return True, _(
            f"敌人小工具已就绪：{msb.name} / {npc.name}",
            f"Enemy helpers ready: {msb.name} / {npc.name}",
        )
    except Exception as exc:  # noqa: BLE001
        return False, _(
            f"敌人小工具编译失败：{exc}",
            f"Enemy helper build failed: {exc}",
        )


def _game_path_status() -> tuple[bool, str]:
    try:
        game = resolve_game_dir()
        return True, _("游戏目录：", "Game folder: ") + str(game)
    except FileNotFoundError as exc:
        return False, str(exc)


def cmd_doctor(_args: argparse.Namespace) -> int:
    _print(_("=== 环境检查 ===", "=== Environment check ==="))
    ok_all = True
    labels = (
        ("Python", "Python", _python_ok),
        (".NET 8 Runtime", ".NET 8 Runtime", _dotnet_ok),
        (".NET 8 SDK", ".NET 8 SDK", _dotnet_sdk_ok),
        ("游戏目录", "Game folder", _game_path_status),
    )
    for zh_label, en_label, fn in labels:
        ok, msg = fn()
        mark = "OK" if ok else _("缺", "MISSING")
        label = en_label if _LANG == "en" else zh_label
        _print(f"[{mark}] {label}: {msg}")
        if not ok and zh_label not in ("游戏目录",):
            # Runtime optional if SDK present; SDK required for scripts helpers
            if zh_label == ".NET 8 Runtime":
                sdk_ok, _sdk_msg = _dotnet_sdk_ok()
                if sdk_ok:
                    continue
            if zh_label == ".NET 8 SDK":
                ok_all = False
            elif zh_label == "Python":
                ok_all = False
            elif zh_label == ".NET 8 Runtime":
                ok_all = False
    cfg = SCRIPT_DIR / "config.json"
    _print(
        f"[--] config: {cfg} "
        + (_("（在）" if cfg.is_file() else "（缺）", "(present)" if cfg.is_file() else "(missing)"))
    )
    from mod_install import is_mod_installed

    try:
        installed = is_mod_installed()
    except Exception:  # noqa: BLE001
        installed = False
    _print(
        f"[{'OK' if installed else _('缺', 'MISSING')}] "
        + _(
            f"模组接线: {'已装' if installed else '未装（先跑 install-mod）'}",
            f"Mod wiring: {'installed' if installed else 'not installed (run install-mod first)'}",
        )
    )
    helpers_ok, helpers_msg = _ensure_enemy_helper_tools()
    _print(f"[{'OK' if helpers_ok else _('缺', 'MISSING')}] {helpers_msg}")
    if not helpers_ok:
        ok_all = False
    if ok_all:
        _print(_("核心运行时已就绪。", "Core runtime is ready."))
        return 0
    _print(
        _(
            "请先运行：python player_run.py install-runtime",
            "Run first: python player_run.py install-runtime",
        )
    )
    return 1


def _winget_available() -> bool:
    return shutil.which("winget") is not None


def _winget_install(package_id: str) -> bool:
    winget = shutil.which("winget")
    if not winget:
        return False
    _print(
        _(
            f"尝试 winget 安装 {package_id} …",
            f"Trying winget install {package_id} ...",
        )
    )
    cmd = [
        winget,
        "install",
        "-e",
        "--id",
        package_id,
        "--accept-package-agreements",
        "--accept-source-agreements",
    ]
    proc = subprocess.run(cmd, check=False)
    return proc.returncode == 0


def cmd_install_runtime(args: argparse.Namespace) -> int:
    py_ok, py_msg = _python_ok()
    sdk_ok, sdk_msg = _dotnet_sdk_ok()
    net_ok, net_msg = _dotnet_ok()
    _print(py_msg)
    _print(sdk_msg)
    _print(net_msg)

    need_install = not (py_ok and sdk_ok)
    used_winget = False
    if need_install:
        if _winget_available():
            used_winget = True
            if not py_ok:
                if not _winget_install(WINGET_PYTHON):
                    _print(
                        _(
                            "winget 安装 Python 未成功，将打开官网。",
                            "winget Python install failed; opening download page.",
                        )
                    )
                    webbrowser.open(PYTHON_DOWNLOAD)
            if not sdk_ok:
                # SDK includes runtimes needed to build/run helpers
                if not _winget_install(WINGET_DOTNET_SDK):
                    _print(
                        _(
                            "winget 安装 .NET 8 SDK 未成功，将打开官网。",
                            "winget .NET 8 SDK install failed; opening download page.",
                        )
                    )
                    webbrowser.open(DOTNET_DOWNLOAD)
            elif not net_ok:
                if not _winget_install(WINGET_DOTNET):
                    webbrowser.open(DOTNET_DOWNLOAD)
        else:
            _print(
                _(
                    "本机没有 winget，打开官方下载页（请手动安装 Python 3.13 与 .NET 8 SDK 后重开命令行）。",
                    "No winget on this PC; opening download pages "
                    "(install Python 3.13 and .NET 8 SDK, then open a new command prompt).",
                )
            )
            if not py_ok:
                webbrowser.open(PYTHON_DOWNLOAD)
            if not sdk_ok:
                webbrowser.open(DOTNET_DOWNLOAD)

    if not args.no_recheck:
        _print(_("重新检查…", "Rechecking..."))
        py_ok2, py_msg2 = _python_ok()
        sdk_ok2, sdk_msg2 = _dotnet_sdk_ok()
        _print(py_msg2)
        _print(sdk_msg2)
        if not (py_ok2 and sdk_ok2):
            _print(
                _(
                    "仍有缺失。若刚装完，请关闭本窗口、新开命令行再跑 doctor。",
                    "Still missing. If you just installed, close this window, "
                    "open a new command prompt, then run doctor.",
                )
                + (
                    _("（winget 可能需管理员）", " (winget may need admin)")
                    if used_winget
                    else ""
                )
            )
            _print(f"Python: {PYTHON_DOWNLOAD}")
            _print(f".NET 8 SDK: {DOTNET_DOWNLOAD}")
            return 1

    _print(_("编译敌人小工具…", "Building enemy helpers..."))
    helpers_ok, helpers_msg = _ensure_enemy_helper_tools()
    _print(helpers_msg)
    if not helpers_ok:
        return 1
    _print(_("安装完成。", "Install complete."))
    return 0


def cmd_install_mod(args: argparse.Namespace) -> int:
    from mod_install import install_mod, save_game_dir

    if args.game_dir:
        game = Path(args.game_dir).expanduser().resolve()
        if not game.is_dir():
            _print(_("目录不存在：", "Folder not found: ") + str(game))
            return 1
        save_game_dir(game)
    else:
        try:
            game = resolve_game_dir()
        except FileNotFoundError:
            _print(
                _(
                    "尚未配置游戏目录。请加参数：\n"
                    '  python player_run.py install-mod --game-dir "D:\\Games\\Elden Ring\\Game"',
                    "Game folder not configured. Pass:\n"
                    '  python player_run.py install-mod --game-dir "D:\\Games\\Elden Ring\\Game"',
                )
            )
            return 1

    result = install_mod(game, force=bool(args.force), dry_run=False)
    for m in result.messages:
        _print(m)
    return 0 if result.ok else 1


def _load_cfg(seed: int | None) -> dict:
    from cnv_randomizer_core import load_config

    path = SCRIPT_DIR / "config.json"
    cfg = load_config(path)
    if seed is not None:
        cfg["seed"] = int(seed)
        path.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _print(_("已写入种子 ", "Wrote seed ") + f"{seed} → {path.name}")
    return cfg


def cmd_generate(args: argparse.Namespace) -> int:
    from mod_install import is_mod_installed
    from cnv_randomizer_core import deploy_runtime_map, run_randomize
    from enemy_apply_runner import run_enemy_apply
    from enemy_randomizer_core import run_enemy_randomize
    from enemy_spawn_io import deploy_enemy_spawn_map

    if not is_mod_installed() and not args.allow_without_mod:
        _print(
            _(
                "尚未安装模组接线。请先：python player_run.py install-mod",
                "Mod not installed. Run: python player_run.py install-mod",
            )
        )
        return 1

    cfg = _load_cfg(args.seed)
    enemy_gui = dict(cfg.get("enemy_gui") or {})
    do_items = bool(enemy_gui.get("page_items_enabled", True))
    do_enemies = bool(enemy_gui.get("page_enemies_enabled", True))
    if args.items_only:
        do_items, do_enemies = True, False
    if args.enemies_only:
        do_items, do_enemies = False, True
    if not do_items and not do_enemies:
        _print(
            _(
                "config 里物品/敌人都关了。请改 enemy_gui.page_items_enabled / page_enemies_enabled",
                "Items and enemies are both off in config. "
                "Set enemy_gui.page_items_enabled / page_enemies_enabled",
            )
        )
        return 1

    ensure_output_dirs()
    seed = int(cfg.get("seed", 1))
    _print(
        f"======== {_('开始生成', 'Generate start')} "
        f"seed={seed} items={do_items} enemies={do_enemies} ========"
    )

    if do_items:
        _print(_("物品：计算…", "Items: computing..."))
        result = run_randomize(cfg, deploy=False)
        dest = deploy_runtime_map(Path(result.runtime_map_path))
        _print(
            _("物品完成 lots=", "Items done lots=")
            + f"{result.stats.get('lots', 0)} → {dest}"
        )

    if do_enemies:
        _print(_("敌人：计算…", "Enemies: computing..."))
        map_filter = enemy_gui.get("map_filter") or None
        if isinstance(map_filter, str):
            map_filter = map_filter.strip() or None
        eresult = run_enemy_randomize(
            cfg,
            seed=seed,
            map_filter=map_filter,
            on_progress=lambda _p, d, t, m: _print(m) if d in (0, t) or (t and d % 500 == 0) else None,
        )
        try:
            from _audit_freeze_pipeline import freeze_gate_detail

            gate, gate_total, gate_samples = freeze_gate_detail(eresult.spawn_map_path)
            if gate_total > 0:
                _print(_("冻怪门禁未通过：", "Freeze gate failed: ") + str(gate))
                for key, lines in (gate_samples or {}).items():
                    for line in lines[:2]:
                        _print(f"  {key}: {line}")
                return 1
            _print(_("冻怪门禁：通过", "Freeze gate: OK"))
        except Exception as exc:  # noqa: BLE001
            _print(_("冻怪门禁跳过：", "Freeze gate skipped: ") + str(exc))

        apply_spawn = eresult.apply_spawn_path or eresult.spawn_map_path
        try:
            deploy_enemy_spawn_map(apply_spawn)
            _print(_("已部署敌人表 → ", "Deployed enemy map → ") + apply_spawn.name)
        except OSError as exc:
            _print(_("敌人表部署失败：", "Enemy map deploy failed: ") + str(exc))
            return 1

        if eresult.slots_replaced <= 0:
            _print(
                _(
                    "敌人替换 0 槽，跳过 MSB 写入",
                    "0 enemy slots replaced; skip MSB write",
                )
            )
            return 1

        if args.skip_apply:
            _print(
                _(
                    "已跳过 MSB apply（--skip-apply）",
                    "Skipped MSB apply (--skip-apply)",
                )
            )
        else:
            _print(_("敌人：写入地图…", "Enemies: writing maps..."))
            apply_result = run_enemy_apply(apply_spawn, map_filter=map_filter)
            _print(
                f"MSB done maps={apply_result.maps_written} "
                f"slots={apply_result.slots_patched}"
            )

    _print(
        _(
            "======== 生成结束：请完全退出游戏后再进 ========",
            "======== Done: fully quit the game, then relaunch ========",
        )
    )
    return 0


def _pid_has_visible_window(pid: int) -> bool:
    """True if *pid* owns at least one visible top-level window (Windows)."""
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found = ctypes.c_int(0)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd: int, _lparam: int) -> bool:
        proc_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if int(proc_id.value) != int(pid):
            return True
        if user32.IsWindowVisible(hwnd) and user32.GetWindow(hwnd, 4) == 0:  # GW_OWNER=4 → top-level-ish
            # Prefer real UI windows (non-zero size)
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                if (rect.right - rect.left) > 50 and (rect.bottom - rect.top) > 50:
                    found.value = 1
                    return False
        return True

    user32.EnumWindows(_enum, 0)
    return bool(found.value)


def _wait_for_gui_window(proc: subprocess.Popen[bytes], *, timeout_s: float = 90.0) -> bool:
    """Block until GUI process shows a visible window, or process exits."""
    import time

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        if proc.pid and _pid_has_visible_window(int(proc.pid)):
            return True
        time.sleep(0.25)
    return proc.poll() is None


def cmd_gui(_args: argparse.Namespace) -> int:
    gui = SCRIPT_DIR / "cnv_randomizer_gui.py"
    if not gui.is_file():
        _print(_("找不到界面脚本：", "GUI script not found: ") + str(gui))
        return 1
    _print(_("正在打开界面，请稍候（黑窗会等到界面出现再关）…",
            "Opening GUI, please wait (this window stays until the GUI appears)..."))
    popen_kwargs: dict = {"cwd": str(SCRIPT_DIR)}
    if sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS — survive bat console close
        popen_kwargs["creationflags"] = 0x00000200 | 0x00000008
        popen_kwargs["close_fds"] = True
    proc = subprocess.Popen([sys.executable, str(gui)], **popen_kwargs)
    if _wait_for_gui_window(proc):
        _print(_("界面已打开，正在关闭本黑窗。", "GUI is up; closing this console."))
        return 0
    if proc.poll() is not None:
        _print(_("界面进程已退出，可能启动失败。", "GUI process exited; launch may have failed."))
        return 1
    _print(
        _(
            "等待超时，但界面进程仍在运行；将关闭黑窗，请再等几秒看是否弹出。",
            "Timed out waiting for the window, but the process is still running; "
            "closing this console — wait a few seconds for the GUI.",
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Randomizer for all — scripts pack CLI (no PyInstaller exe)"
    )
    p.add_argument(
        "--lang",
        choices=("zh", "en"),
        default="zh",
        help="CLI language (EN bats pass --lang en)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="Check Python / .NET 8 / game folder / mod wiring")

    ir = sub.add_parser("install-runtime", help="Install Python 3.13 and .NET 8 when possible")
    ir.add_argument(
        "--no-recheck",
        action="store_true",
        help="Install only; skip second check",
    )

    im = sub.add_parser("install-mod", help="Install mod wiring into Convergence Game folder")
    im.add_argument("--game-dir", type=str, default=None)
    im.add_argument("--force", action="store_true")

    gen = sub.add_parser("generate", help="Generate items/enemies from config.json")
    gen.add_argument("--seed", type=int, default=None)
    gen.add_argument("--items-only", action="store_true")
    gen.add_argument("--enemies-only", action="store_true")
    gen.add_argument("--skip-apply", action="store_true", help="Tables only; no MSB write")
    gen.add_argument(
        "--allow-without-mod",
        action="store_true",
        help="Allow generate without mod wiring (debug)",
    )

    sub.add_parser("gui", help="Open GUI with this Python")
    return p


def main(argv: list[str] | None = None) -> int:
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    os.chdir(SCRIPT_DIR)
    parser = build_parser()
    args = parser.parse_args(argv)
    set_lang(getattr(args, "lang", "zh"))
    handlers = {
        "doctor": cmd_doctor,
        "install-runtime": cmd_install_runtime,
        "install-mod": cmd_install_mod,
        "generate": cmd_generate,
        "gui": cmd_gui,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
