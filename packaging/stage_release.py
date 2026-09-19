#!/usr/bin/env python3
"""Stage Randomizer for all v1.0.0 release zip (onedir exe at package root + data/).

Contract: .ai/docs/发行包契约.md
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CNV_DIR = REPO_ROOT / "cnv_randomizer"
POC_DIR = REPO_ROOT / "cnv_enemy_poc"
DIST_ROOT = REPO_ROOT / "dist"
# PyInstaller skip-cache lives outside dist/ so dist/ can be zip-only
ONEDIR_CACHE = Path(__file__).resolve().parent / "_onedir_cache"
PRODUCT = "Randomizer-for-all"
VERSION = "1.0.0"
HOOK_VERSION = "8.9.46"
APP_NAME = "RandomizerForAll"

CACHE_KEEP = (
    "enemy_index.json",
    "enemy_slot_prep.json.gz",
    "enemy_slot_prep.meta.json",
    "pickup_slot_index.json",
    "enemy_slot_density.json",
    "enemy_slot_density.meta.json",
    "bundle_catalog.json",
    "bundle_slot_compat.json",
    "slot_tags.json",
    "donor_slot_compat.json",
    "item_names_engus_dlc02.json",
    "item_names_zhocn_dlc02.json",
    "whitelist_donor_slot_receptor.json",
    "pool_npc_slot_caps.json",
    "enemy_model_registry.json",
    "enemy_slot_catalog.json",
    "enemy_slot_catalog.meta.json",
)

# Keep whole dirs under cache/ (offline slot tables for faster first generate)
CACHE_KEEP_DIRS = ("offline",)

JSON_SKIP = {
    "maintainer.local.json",
    "gatefront_test_lab.json",
    "test_map_apply_modes.json",
}


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), check=True)


def rebuild_prep() -> None:
    """Ensure enemy_slot_prep matches PREP_VERSION + current fingerprints."""
    sys.path.insert(0, str(CNV_DIR))
    os.chdir(CNV_DIR)
    from enemy_index_pipeline import load_enemy_index
    from enemy_slot_prep import (
        DEFAULT_SLOT_PREP_PATH,
        PREP_META_KEYS,
        PREP_VERSION,
        build_slot_prep,
        explain_prep_cache_miss,
        is_slot_prep_valid,
        prep_meta,
        read_slot_prep_meta_record,
        slot_prep_meta_path,
    )
    from paths import CACHE_DIR, resolve_game_dir

    gz = CACHE_DIR / "enemy_slot_prep.json.gz"
    if gz.is_file() and is_slot_prep_valid(DEFAULT_SLOT_PREP_PATH):
        print(f"[prep] valid (PREP_VERSION={PREP_VERSION}, fingerprints ok)", flush=True)
        return

    # Zip/copy used to break mtime-based donor_msb_compat only — restamp sidecar
    # when every other fingerprint still matches (no full 5–8min rebuild).
    record = read_slot_prep_meta_record()
    if gz.is_file() and record is not None and int(record.get("version", 0)) == PREP_VERSION:
        current = prep_meta()
        stored = record.get("meta") or {}
        other_ok = all(
            str(stored.get(k, "")) == str(current.get(k, ""))
            for k in PREP_META_KEYS
            if k != "donor_msb_compat"
        )
        if other_ok:
            record["meta"] = {k: str(current.get(k, "")) for k in PREP_META_KEYS}
            # Keep or clear release_cache? Dev restamp should clear — release stamp is pack-only.
            record.pop("release_cache", None)
            slot_prep_meta_path(DEFAULT_SLOT_PREP_PATH).write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if is_slot_prep_valid(DEFAULT_SLOT_PREP_PATH):
                print(
                    "[prep] restamped donor_msb_compat fingerprint (zip-safe); skipped rebuild",
                    flush=True,
                )
                return

    reason = explain_prep_cache_miss()
    ver = int((record or {}).get("version", 0))
    print(f"[prep] rebuilding ({reason}; meta_ver={ver} → {PREP_VERSION}) …", flush=True)
    index = load_enemy_index()
    cats = json.loads(
        (CNV_DIR / "enemy_categories.json").read_text(encoding="utf-8")
    )
    npc_csv = resolve_game_dir() / "csv"
    if not npc_csv.is_dir():
        raise SystemExit(f"Game csv missing: {npc_csv}")
    out = build_slot_prep(
        index,
        cats,
        dlc_pool_mode="mixed",
        npc_csv_dir=npc_csv,
        on_progress=lambda *_a, **_k: None,
    )
    if not is_slot_prep_valid(out or DEFAULT_SLOT_PREP_PATH):
        raise SystemExit(
            f"prep rebuild still invalid: {explain_prep_cache_miss()}"
        )
    print(f"[prep] ok → {out}", flush=True)


def build_dotnet() -> None:
    _run(
        ["dotnet", "build", "MsbEnemyPoc.csproj", "-c", "Release"],
        cwd=POC_DIR / "MsbEnemyPoc",
    )
    _run(
        ["dotnet", "build", "NpcSoulPatch.csproj", "-c", "Release"],
        cwd=POC_DIR / "NpcSoulPatch",
    )


def ensure_dll() -> Path:
    candidates = [
        REPO_ROOT / "bin" / "cnv_pickup_hook.dll",
        Path(r"V:\games\Elden Ring\Game\mod\dll\cnv_pickup_hook.dll"),
    ]
    for path in candidates:
        if path.is_file():
            dest = REPO_ROOT / "bin" / "cnv_pickup_hook.dll"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if path.resolve() != dest.resolve():
                shutil.copy2(path, dest)
            return dest
    raise SystemExit("cnv_pickup_hook.dll not found (expected repo bin/ or Game/mod/dll/)")


def write_config_template(dest: Path) -> None:
    src = CNV_DIR / "config.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    # No machine-absolute paths in the shipped template.
    data["csv_dir"] = "csv"
    data.pop("game_dir", None)
    # Release builds: hide maintainer / test-lab buttons.
    data["maintainer_gui"] = False
    data.setdefault("ui_lang", "zh")
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_game_csv(dst: Path) -> None:
    """Copy Convergence Game/csv into the package for offline item randomize."""
    sys.path.insert(0, str(CNV_DIR))
    from paths import resolve_game_dir

    src = resolve_game_dir() / "csv"
    if not src.is_dir():
        raise SystemExit(f"Game csv missing for packaging: {src}")
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    n = 0
    for path in sorted(src.glob("*.csv")):
        shutil.copy2(path, dst / path.name)
        n += 1
    if n < 10:
        raise SystemExit(f"too few csv files copied from {src}: {n}")
    print(f"[csv] shipped {n} files → {dst}", flush=True)


def copy_tree_filtered(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    ignore = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        "output",
        "tests",
        "test_lab",
        "game_path.json",
        "maintainer.local.json",
        "_diag_*",
        "_probe_*",
        "_tmp*",
        "_peek*",
        "_ai_cmp",
        "_debug",
        "_tools*",
        "docs",
        "*.pkl",
        "enemy_slot_prep.json",  # ship .gz only
        "enemy_index.raw.json",
        "IMPORT_CSV_SMITHBOX.txt",
        "MERGE_WITHOUT_SMITHBOX.txt",
        "SMITHBOX_*.txt",
        "APPLY_*.bat",
        "APPLY_*.py",
    )
    shutil.copytree(src, dst, ignore=ignore)


def stage_data(stage: Path) -> None:
    data = stage / "data"
    if data.exists():
        shutil.rmtree(data)
    data.mkdir(parents=True)

    cnv_dst = data / "cnv_randomizer"
    copy_tree_filtered(CNV_DIR, cnv_dst)

    # Trim cache: keep allowlisted files + offline/ dir (slot tables)
    cache_dst = cnv_dst / "cache"
    if cache_dst.is_dir():
        for child in list(cache_dst.iterdir()):
            if child.is_dir():
                if child.name not in CACHE_KEEP_DIRS:
                    shutil.rmtree(child)
                continue
            if child.name not in CACHE_KEEP and child.name != "README.txt":
                child.unlink(missing_ok=True)

    # Drop skipped JSON at cnv root
    for name in JSON_SKIP:
        (cnv_dst / name).unlink(missing_ok=True)
    write_config_template(cnv_dst / "config.json")
    (cnv_dst / "game_path.json").unlink(missing_ok=True)

    # Ship Game/csv for offline item generate (csv_dir=csv)
    _copy_game_csv(cnv_dst / "csv")

    # 分类开关物品池 + 离线参数大表
    contract_dst = data / "捐皮契约"
    contract_dst.mkdir(parents=True, exist_ok=True)
    for name in ("分类开关物品池_当前.json", "离线参数大表.json"):
        src = REPO_ROOT / "捐皮契约" / name
        if not src.is_file():
            raise SystemExit(f"missing {src}")
        shutil.copy2(src, contract_dst / name)

    # DLL
    dll = ensure_dll()
    bin_dst = data / "bin"
    bin_dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dll, bin_dst / "cnv_pickup_hook.dll")

    # Dotnet tools in paths expected by code
    for proj, exe_name in (
        ("MsbEnemyPoc", "MsbEnemyPoc.exe"),
        ("NpcSoulPatch", "NpcSoulPatch.exe"),
    ):
        src_dir = POC_DIR / proj / "bin" / "Release" / "net8.0"
        if not (src_dir / exe_name).is_file():
            raise SystemExit(f"missing {src_dir / exe_name}")
        dst_dir = data / "cnv_enemy_poc" / proj / "bin" / "Release" / "net8.0"
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        shutil.copytree(
            src_dir,
            dst_dir,
            ignore=shutil.ignore_patterns("*.pdb", "*.xml", "ref", "refs"),
        )

    _sanitize_shipped_json_paths(data)


def assert_shipped_prep_ready(stage: Path) -> None:
    """Zip must ship release_cache stamped prep (frozen skips fingerprints)."""
    sys.path.insert(0, str(CNV_DIR))
    from enemy_slot_prep import (
        DEFAULT_SLOT_PREP_PATH,
        PREP_VERSION,
        explain_prep_cache_miss,
        is_slot_prep_valid,
        read_slot_prep_meta_record,
        stamp_release_prep_cache,
    )

    data = stage / "data" / "cnv_randomizer"
    gz = data / "cache" / "enemy_slot_prep.json.gz"
    meta_p = data / "cache" / "enemy_slot_prep.meta.json"
    if not gz.is_file() or not meta_p.is_file():
        raise SystemExit("shipped prep gz/meta missing under data/cnv_randomizer/cache/")
    for name in (
        "donor_pool_review_allowlist.json",
        "donor_pool_review_manual_excludes.json",
        "enemy_categories.json",
        "enemy_archetypes.json",
    ):
        src, dst = CNV_DIR / name, data / name
        if src.is_file() and dst.is_file() and src.read_bytes() != dst.read_bytes():
            raise SystemExit(
                f"sanitize changed {name}; fix sanitize or rebuild prep after staging"
            )
    if not is_slot_prep_valid(DEFAULT_SLOT_PREP_PATH):
        raise SystemExit(
            f"live prep invalid before zip: {explain_prep_cache_miss()}"
        )
    # Stamp live + staged: release cache is a special shipped artifact.
    stamp_release_prep_cache(DEFAULT_SLOT_PREP_PATH)
    stamp_release_prep_cache(data / "cache" / "enemy_slot_prep.json")
    staged_rec = read_slot_prep_meta_record(data / "cache" / "enemy_slot_prep.json")
    if not staged_rec or not staged_rec.get("release_cache"):
        raise SystemExit("staged prep missing release_cache=true")
    if int(staged_rec.get("version", 0)) != PREP_VERSION:
        raise SystemExit("staged prep version mismatch after release stamp")
    # Simulate frozen trust path
    old_frozen = getattr(sys, "frozen", False)
    had_frozen = hasattr(sys, "frozen")
    try:
        sys.frozen = True  # type: ignore[attr-defined]
        if not is_slot_prep_valid(data / "cache" / "enemy_slot_prep.json"):
            raise SystemExit("frozen release_cache trust failed on staged prep")
    finally:
        if had_frozen:
            sys.frozen = old_frozen  # type: ignore[attr-defined]
        elif hasattr(sys, "frozen"):
            delattr(sys, "frozen")
    print("[prep] shipped release_cache stamped (frozen skips fingerprints)", flush=True)


def _sanitize_shipped_json_paths(data_root: Path) -> None:
    """Rewrite developer absolute paths to package-relative paths in shipped text/JSON."""
    # Longest prefixes first → SCRIPT_DIR-relative, then REPO_ROOT-relative.
    prefixes = (
        r"V:\1_mel\Ringrandom\cnv_randomizer\\",
        r"V:/1_mel/Ringrandom/cnv_randomizer/",
        r"V:\\1_mel\\Ringrandom\\cnv_randomizer\\",
        r"V://1_mel/Ringrandom/cnv_randomizer/",
        r"V:\1_mel\Ringrandom\\",
        r"V:/1_mel/Ringrandom/",
        r"V:\\1_mel\\Ringrandom\\",
        r"V://1_mel/Ringrandom/",
        r"V:\games\Elden Ring\Game\\",
        r"V:/games/Elden Ring/Game/",
        r"V:\\games\\Elden Ring\\Game\\",
    )
    for path in data_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".json", ".txt", ".md", ".toml", ".ini"}:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        out = text
        for pref in prefixes:
            if pref in out:
                out = out.replace(pref, "")
        # Placeholder for leftover Game-dir examples in any remaining notes
        out = out.replace(r"V:\games\Elden Ring\Game", "<Game>")
        out = out.replace(r"V:/games/Elden Ring/Game", "<Game>")
        out = out.replace(r"V:\\games\\Elden Ring\\Game", "<Game>")
        # Any remaining drive-letter Ringrandom / Game path → basename
        if "V:\\" in out or "V:/" in out or "C:\\Users\\" in out or "C:/Users/" in out:
            try:
                obj = json.loads(out)
            except json.JSONDecodeError:
                path.write_text(out, encoding="utf-8")
                continue

            def _clean(value: object) -> object:
                if isinstance(value, str):
                    if value.startswith(("V:\\", "V:/", "C:\\", "C:/")):
                        return Path(value.replace("\\", "/")).name
                    return value
                if isinstance(value, dict):
                    return {k: _clean(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [_clean(v) for v in value]
                return value

            out = json.dumps(_clean(obj), ensure_ascii=False, indent=2) + "\n"
        if out != text:
            path.write_text(out, encoding="utf-8")


def write_docs(stage: Path, prep_ver: int) -> None:
    (stage / "VERSION.txt").write_text(
        "\n".join(
            [
                f"product=Randomizer for all",
                f"randomizer={VERSION}",
                f"hook={HOOK_VERSION}",
                f"prep={prep_ver}",
                "scope=Convergence 3.0 + ME3",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (stage / "CHANGELOG.txt").write_text(
        f"Randomizer for all {VERSION}\n"
        "- First public onedir package: enemy + pickup + install-to-game\n"
        "- Current support: The Convergence 3.0 + ME3 only\n",
        encoding="utf-8",
    )
    cn = stage / "README_安装_中文.txt"
    cn.write_text(
        f"""Randomizer for all {VERSION}
================================

本包用于：法魂 Convergence 3.0 + ME3。
需要：Windows 10/11、.NET 8 运行时、已能正常进法魂的游戏目录。

安装 6 步
---------
1. 已安装法魂 Convergence 3.0，能正常进游戏。
2. 解压本包到任意目录（路径尽量短、少用奇怪符号）。
3. 打开 {APP_NAME}.exe（解压后的包根）→「安装mod到游戏」页 → 选法环 Game 目录 →「安装本模组到游戏」。
   （本步只改法魂原来的启动配置，不会另做一个启动器。）
4. 设种子 / 概率 →「开始生成」（约数分钟；未安装则不能生成）。
5. 确认 Game\\mod\\cnv_enemy\\ 与 mod\\dll\\ 下有新文件。
6. 怎么进游戏（重要）：
   - 先完全退出游戏（任务栏图标也要退出）。
   - 再用法魂原来的方式启动——常见是双击 Game 目录里的 Start_Convergence_ME3.bat。
   - 你平时用法魂进游戏的那个入口也可以；不要直接单独开 eldenring.exe。
   - 建议用新档，或去尚未清怪的区域验证。

卸载：安装页「卸下本模组接线」。

要加载哪个 dll（手动接线 / 自写 bat 的人看这里）
------------------------------------------------
地上拾取用的 dll：
  游戏里路径：Game\\mod\\dll\\cnv_pickup_hook.dll
  本包里源文件：data\\bin\\cnv_pickup_hook.dll
  （用软件「安装」会自动拷过去；手动的人请自己拷到上面游戏路径。）

怎么让游戏加载它：
  不是在 bat 里写加载 dll，而是改 Game\\me3\\convergence.me3，加上：

  [[package]]
  id = "cnv-enemy-poc"
  path = "./../mod/cnv_enemy"
  load_after = [{{ id = "convergence-er", optional = false }}]

  [[natives]]
  path = './../mod/dll/cnv_pickup_hook.dll'

  （敌人换怪靠上面的 package；地上拾取靠 natives 这条 dll。）

自写 bat 示例（放在 Game 目录根，用 ME3 启动法魂配置）：

  @echo off
  cd /d "%~dp0"
  start .\\me3\\Windows\\me3.exe launch --auto-detect -p ".\\me3\\convergence.me3"

注意
----
- 杀软可能误报；请添加解压目录信任。
- 生成后必须完全退出再进游戏，随机才会生效。
""",
        encoding="utf-8",
    )
    en = stage / "README_Install_EN.txt"
    en.write_text(
        f"""Randomizer for all {VERSION}
================================

For: The Convergence 3.0 + ME3.
Requires: Windows 10/11, .NET 8 Runtime, a working Convergence install.

Install (6 steps)
-----------------
1. Install Convergence 3.0 and confirm the game launches.
2. Extract this zip somewhere short/simple.
3. Run {APP_NAME}.exe at the unzipped folder root → Install tab → pick Elden Ring Game folder → Install mod into game.
   (This updates Convergence/ME3 config; it does not create a separate launcher.)
4. Set seed / weights → Generate (a few minutes; blocked until installed).
5. Confirm Game\\mod\\cnv_enemy\\ and mod\\dll\\ updated.
6. How to launch (important):
   - Fully quit the game (also from the taskbar).
   - Launch the same way you normally start Convergence — often Start_Convergence_ME3.bat in the Game folder.
   - Do not start eldenring.exe alone.
   - Prefer a new save or uncleared areas to verify.

Uninstall: use “Remove mod wiring” on the Install tab.

Which DLL to load (manual wiring / custom .bat)
-----------------------------------------------
Pickup DLL:
  In-game path: Game\\mod\\dll\\cnv_pickup_hook.dll
  In this zip: data\\bin\\cnv_pickup_hook.dll
  (Install tab copies it for you; manual users copy it to the game path above.)

How it loads:
  Do NOT LoadLibrary from the .bat. Edit Game\\me3\\convergence.me3 and add:

  [[package]]
  id = "cnv-enemy-poc"
  path = "./../mod/cnv_enemy"
  load_after = [{{ id = "convergence-er", optional = false }}]

  [[natives]]
  path = './../mod/dll/cnv_pickup_hook.dll'

  (Enemy overlays use the package; ground loot uses the natives DLL.)

Example .bat (place in Game folder root; starts ME3 with Convergence profile):

  @echo off
  cd /d "%~dp0"
  start .\\me3\\Windows\\me3.exe launch --auto-detect -p ".\\me3\\convergence.me3"

Notes
-----
- Antivirus may flag PyInstaller builds; allowlist the folder.
- Fully quit the game after generating before launching again.
""",
        encoding="utf-8",
    )


def run_pyinstaller(stage: Path) -> None:
    """Build onedir and flatten exe + _internal into package root (no app/)."""
    build_root = Path(__file__).resolve().parent / "_build"
    work = build_root / "pyi_work"
    spec_dir = build_root / "pyi_spec"
    dist_tmp = build_root / f"pyi_dist_{PRODUCT}-{VERSION}"
    if build_root.exists():
        shutil.rmtree(build_root, ignore_errors=True)
    dist_tmp.mkdir(parents=True)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        "--onedir",
        "--noupx",
        # Scatter stdlib/.pyc instead of base_library.zip (no zip-in-zip).
        "--debug=noarchive",
        "--version-file",
        str(Path(__file__).resolve().parent / "RandomizerForAll.version.txt"),
        "--paths",
        str(CNV_DIR),
        "--distpath",
        str(dist_tmp),
        "--workpath",
        str(work),
        "--specpath",
        str(spec_dir),
        str(CNV_DIR / "cnv_randomizer_gui.py"),
    ]
    _run(cmd)
    built = dist_tmp / APP_NAME
    if not (built / f"{APP_NAME}.exe").is_file():
        raise SystemExit(f"PyInstaller missing exe under {built}")
    for child in list(built.iterdir()):
        dest = stage / child.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.move(str(child), str(dest))
    shutil.rmtree(build_root, ignore_errors=True)


def _onedir_names() -> tuple[str, ...]:
    return (f"{APP_NAME}.exe", "_internal")


def _copy_onedir_parts(src_root: Path, dest_root: Path) -> None:
    dest_root.mkdir(parents=True, exist_ok=True)
    for name in _onedir_names():
        src = src_root / name
        dest = dest_root / name
        if not src.exists():
            raise SystemExit(f"missing onedir part: {src}")
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)


def make_zip(stage: Path) -> Path:
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    zip_path = DIST_ROOT / f"{PRODUCT}-{VERSION}.zip"
    if zip_path.is_file():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in stage.rglob("*"):
            if path.is_file():
                # skip huge uncompressed prep json if any slipped in
                if path.name == "enemy_slot_prep.json":
                    continue
                if path.name == "game_path.json":
                    continue
                arc = f"{PRODUCT}-{VERSION}/{path.relative_to(stage).as_posix()}"
                # UTF-8 filenames (Chinese README) — flag 0x800
                info = zipfile.ZipInfo(filename=arc)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.flag_bits |= 0x800
                mtime = path.stat().st_mtime
                info.date_time = __import__("time").localtime(mtime)[:6]
                zf.writestr(info, path.read_bytes())
    return zip_path


_NESTED_ARCHIVE_SUFFIXES = (".zip", ".pyz", ".whl", ".egg", ".jar")


def assert_no_nested_archives(stage: Path) -> None:
    """Fail pack if stage still contains nested archives (zip-in-zip AV noise)."""
    bad: list[str] = []
    for path in stage.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in _NESTED_ARCHIVE_SUFFIXES:
            bad.append(path.relative_to(stage).as_posix())
    if bad:
        raise SystemExit(
            "nested archives in stage (forbidden; use --debug=noarchive / unpack):\n  "
            + "\n  ".join(bad[:40])
        )


def assert_relative_paths_only(stage: Path) -> None:
    """Fail pack if shipped text/json still contains developer absolute paths."""
    needles = (
        "V:\\1_mel\\Ringrandom",
        "V:/1_mel/Ringrandom",
        "V:\\games\\Elden Ring",
        "V:/games/Elden Ring",
        "C:\\Users\\Administrator",
        "C:/Users/Administrator",
    )
    bad: list[str] = []
    for path in stage.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".json", ".txt", ".md", ".csv", ".toml", ".ini"}:
            continue
        if path.name == "game_path.json":
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            continue
        for n in needles:
            if n in text:
                bad.append(f"{path.relative_to(stage).as_posix()}: contains {n!r}")
                break
    if bad:
        raise SystemExit(
            "absolute paths leaked into stage (fix before zip):\n  " + "\n  ".join(bad[:20])
        )


def cleanup_dist_keep_zip_only(zip_path: Path) -> None:
    """Contract: dist/ must only contain the release zip after a successful pack."""
    import time

    # Unlocked by closing leftover release exe/handle before rmtree
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", f"{APP_NAME}.exe"],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass
    time.sleep(0.3)

    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    keep_name = zip_path.name

    def _rm(path: Path) -> None:
        def _onerr(func, p, _exc) -> None:  # noqa: ANN001
            try:
                os.chmod(p, 0o700)
                func(p)
            except OSError:
                pass

        for _ in range(5):
            try:
                if path.is_dir():
                    shutil.rmtree(path, onerror=_onerr)
                elif path.exists():
                    path.unlink()
                if not path.exists():
                    return
            except OSError:
                time.sleep(0.4)
        raise SystemExit(f"cannot remove {path}")

    for child in list(DIST_ROOT.iterdir()):
        if child.name == keep_name:
            continue
        _rm(child)
    left = sorted(p.name for p in DIST_ROOT.iterdir())
    if left != [keep_name]:
        raise SystemExit(f"dist/ cleanup failed, still has: {left}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-prep", action="store_true")
    ap.add_argument("--skip-dotnet", action="store_true")
    ap.add_argument("--skip-pyinstaller", action="store_true")
    args = ap.parse_args()

    if not args.skip_prep:
        rebuild_prep()
    if not args.skip_dotnet:
        build_dotnet()
    ensure_dll()

    stage = DIST_ROOT / f"_stage_{PRODUCT}-{VERSION}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    prev_onedir = ONEDIR_CACHE / f"{PRODUCT}-{VERSION}"
    if args.skip_pyinstaller:
        if not (prev_onedir / f"{APP_NAME}.exe").is_file():
            raise SystemExit(
                "--skip-pyinstaller needs a prior onedir at "
                f"{prev_onedir}; run once without --skip-pyinstaller first"
            )
        _copy_onedir_parts(prev_onedir, stage)
    else:
        run_pyinstaller(stage)
        if prev_onedir.exists():
            shutil.rmtree(prev_onedir)
        prev_onedir.parent.mkdir(parents=True, exist_ok=True)
        _copy_onedir_parts(stage, prev_onedir)

    stage_data(stage)
    assert_shipped_prep_ready(stage)

    sys.path.insert(0, str(CNV_DIR))
    from enemy_slot_prep import PREP_VERSION, read_slot_prep_meta_record

    meta = read_slot_prep_meta_record()
    prep_ver = int((meta or {}).get("version", PREP_VERSION))
    write_docs(stage, prep_ver)

    assert_relative_paths_only(stage)
    assert_no_nested_archives(stage)
    zip_path = make_zip(stage)
    cleanup_dist_keep_zip_only(zip_path)
    print(f"[ok] zip: {zip_path} ({zip_path.stat().st_size // (1024 * 1024)} MB)")
    print(f"[ok] dist/ contains only: {zip_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
