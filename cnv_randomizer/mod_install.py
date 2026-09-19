"""Install CNV mod wiring into a user-selected Elden Ring Game directory.

Contract: .ai/docs/装进游戏契约.md
"""

from __future__ import annotations

import ctypes
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from paths import REPO_ROOT, SCRIPT_DIR

# ProductVersion 2.6.2.0 == app 1.16.2 (community / hook convention)
ER_REQUIRED_PRODUCT = "2.6.2.0"
ER_REQUIRED_APP_LABEL = "1.16.2"
CNV_REQUIRED_LABEL = "Convergence 3.0"

PACKAGE_ID = "cnv-enemy-poc"
PACKAGE_BLOCK = (
    '[[package]]\n'
    f'id = "{PACKAGE_ID}"\n'
    'path = "./../mod/cnv_enemy"\n'
    'load_after = [{ id = "convergence-er", optional = false }]\n'
)
NATIVES_PATH = "./../mod/dll/cnv_pickup_hook.dll"
NATIVES_BLOCK = f"[[natives]]\npath = '{NATIVES_PATH}'\n"

DLL_NAME = "cnv_pickup_hook.dll"
GAME_PATH_JSON_NAME = "game_path.json"

_PROCESS_NAMES = (
    "eldenring.exe",
    "start_protected_game.exe",
    "me3.exe",
    "me3-launcher.exe",
)


@dataclass
class ErDetect:
    ok: bool
    product_version: str = ""
    app_label: str = ""
    detail: str = ""


@dataclass
class CnvDetect:
    likely_ok: bool
    signals: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class DetectReport:
    game_dir: Path
    er: ErDetect
    cnv: CnvDetect
    me3_path: Path | None
    exe_path: Path | None
    process_running: bool
    process_detail: str = ""


@dataclass
class PreviewItem:
    action: str
    path: str
    note: str = ""


@dataclass
class InstallResult:
    ok: bool
    messages: list[str] = field(default_factory=list)
    preview: list[PreviewItem] = field(default_factory=list)


def game_path_config_candidates() -> list[Path]:
    """Prefer GUI-adjacent then repo root (dev checkout)."""
    return [
        SCRIPT_DIR / GAME_PATH_JSON_NAME,
        SCRIPT_DIR.parent / GAME_PATH_JSON_NAME,
        REPO_ROOT / GAME_PATH_JSON_NAME,
    ]


def load_saved_game_dir() -> Path | None:
    for cfg in game_path_config_candidates():
        if not cfg.is_file():
            continue
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        raw = str(data.get("game_dir", "")).strip()
        if not raw:
            continue
        path = Path(raw)
        if path.is_dir():
            return path
    return None


def save_game_dir(game_dir: Path) -> Path:
    """Write game_dir under SCRIPT_DIR (frozen-safe); also repo root in dev."""
    import sys

    from paths import clear_game_dir_cache

    game_dir = game_dir.resolve()
    payload = json.dumps({"game_dir": str(game_dir)}, ensure_ascii=False, indent=2) + "\n"
    primary = SCRIPT_DIR / GAME_PATH_JSON_NAME
    primary.parent.mkdir(parents=True, exist_ok=True)
    primary.write_text(payload, encoding="utf-8")
    # Dev checkout: CLI tools often look at repo-root game_path.json
    if not getattr(sys, "frozen", False):
        alt = REPO_ROOT / GAME_PATH_JSON_NAME
        if alt.resolve() != primary.resolve():
            alt.write_text(payload, encoding="utf-8")
    # Warmup / first probe may have missed before install; drop sticky miss.
    clear_game_dir_cache()
    return primary


def find_dll_source() -> Path | None:
    candidates = [
        REPO_ROOT / "bin" / DLL_NAME,
        SCRIPT_DIR.parent / "bin" / DLL_NAME,
        SCRIPT_DIR / "bin" / DLL_NAME,
        REPO_ROOT / "cnv_pickup_hook" / "bin" / DLL_NAME,
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _product_version(exe: Path) -> str:
    """Read PE ProductVersion via Win32 Version APIs."""
    path = str(exe)
    size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return ""
    buf = ctypes.create_string_buffer(size)
    if not ctypes.windll.version.GetFileVersionInfoW(path, 0, size, buf):
        return ""
    # Prefer ProductVersion string translation 040904B0 then any
    for query in (
        r"\StringFileInfo\040904B0\ProductVersion",
        r"\StringFileInfo\040904b0\ProductVersion",
    ):
        ptr = ctypes.c_void_p()
        length = ctypes.c_uint()
        if ctypes.windll.version.VerQueryValueW(
            buf, query, ctypes.byref(ptr), ctypes.byref(length)
        ):
            if ptr.value and length.value:
                return ctypes.wstring_at(ptr, length.value).strip("\x00").strip()
    # Fallback: VS_FIXEDFILEINFO
    ptr = ctypes.c_void_p()
    length = ctypes.c_uint()
    if ctypes.windll.version.VerQueryValueW(
        buf, r"\\", ctypes.byref(ptr), ctypes.byref(length)
    ):
        # WORD pair: FileVersionMS / FileVersionLS
        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [
                ("dwSignature", ctypes.c_uint32),
                ("dwStrucVersion", ctypes.c_uint32),
                ("dwFileVersionMS", ctypes.c_uint32),
                ("dwFileVersionLS", ctypes.c_uint32),
                ("dwProductVersionMS", ctypes.c_uint32),
                ("dwProductVersionLS", ctypes.c_uint32),
                ("dwFileFlagsMask", ctypes.c_uint32),
                ("dwFileFlags", ctypes.c_uint32),
                ("dwFileOS", ctypes.c_uint32),
                ("dwFileType", ctypes.c_uint32),
                ("dwFileSubtype", ctypes.c_uint32),
                ("dwFileDateMS", ctypes.c_uint32),
                ("dwFileDateLS", ctypes.c_uint32),
            ]

        info = VS_FIXEDFILEINFO.from_address(ptr.value)
        ms, ls = info.dwProductVersionMS, info.dwProductVersionLS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    return ""


def _product_to_app_label(product: str) -> str:
    if product == ER_REQUIRED_PRODUCT or product.startswith("2.6.2"):
        return ER_REQUIRED_APP_LABEL
    return product or "未知"


def detect_elden_ring(game_dir: Path) -> ErDetect:
    exe = game_dir / "eldenring.exe"
    if not exe.is_file():
        return ErDetect(False, detail="未找到 eldenring.exe（请选到 Game 文件夹）")
    product = _product_version(exe)
    label = _product_to_app_label(product)
    ok = product == ER_REQUIRED_PRODUCT or product.startswith("2.6.2.")
    if ok:
        detail = f"法环约 {label}（ProductVersion={product or '空'}）"
    else:
        detail = (
            f"期望法环 {ER_REQUIRED_APP_LABEL}（ProductVersion {ER_REQUIRED_PRODUCT}），"
            f"当前={product or '读不到'}（约 {label}）"
        )
    return ErDetect(ok=ok, product_version=product, app_label=label, detail=detail)


def detect_convergence(game_dir: Path) -> CnvDetect:
    signals: list[str] = []
    me3 = game_dir / "me3" / "convergence.me3"
    if not me3.is_file():
        return CnvDetect(
            False,
            signals,
            detail="未找到 me3/convergence.me3（请先装好法魂 + ME3）",
        )
    signals.append("存在 me3/convergence.me3")
    text = me3.read_text(encoding="utf-8", errors="replace")
    if "convergence-er" in text:
        signals.append("me3 含 convergence-er")
    map_dir = game_dir / "mod" / "map"
    if map_dir.is_dir():
        signals.append("存在 mod/map")
    likely = "convergence-er" in text
    if likely and map_dir.is_dir():
        detail = "法魂迹象正常（ME3 + convergence-er + mod/map）"
    elif likely:
        detail = "已有 convergence-er，但未看到 mod/map（仍可能是法魂）"
    else:
        detail = "convergence.me3 中未见 convergence-er，可能不是法魂 3.0 环境"
    return CnvDetect(likely_ok=likely, signals=signals, detail=detail)


def _process_running() -> tuple[bool, str]:
    # Toolhelp32 snapshot
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == ctypes.c_void_p(-1).value or snap == -1:
        return False, "无法枚举进程（已跳过进程检测）"
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        found: list[str] = []
        want = {n.lower() for n in _PROCESS_NAMES}
        if kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                name = entry.szExeFile.lower()
                if name in want:
                    found.append(entry.szExeFile)
                if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
        if found:
            uniq = sorted(set(found))
            return True, "正在运行：" + "、".join(uniq) + " — 请完全退出后再装"
        return False, ""
    finally:
        kernel32.CloseHandle(snap)


def detect_all(game_dir: Path) -> DetectReport:
    game_dir = Path(game_dir)
    er = detect_elden_ring(game_dir)
    cnv = detect_convergence(game_dir)
    running, proc_detail = _process_running()
    me3 = game_dir / "me3" / "convergence.me3"
    exe = game_dir / "eldenring.exe"
    return DetectReport(
        game_dir=game_dir,
        er=er,
        cnv=cnv,
        me3_path=me3 if me3.is_file() else None,
        exe_path=exe if exe.is_file() else None,
        process_running=running,
        process_detail=proc_detail,
    )


def _me3_has_package(text: str) -> bool:
    return bool(
        re.search(
            rf'id\s*=\s*["\']{re.escape(PACKAGE_ID)}["\']',
            text,
            flags=re.IGNORECASE,
        )
    )


def _me3_has_natives(text: str) -> bool:
    return "cnv_pickup_hook.dll" in text and "[[natives]]" in text


def is_mod_installed(game_dir: Path | None = None) -> bool:
    if game_dir is None:
        game_dir = load_saved_game_dir()
    if game_dir is None:
        try:
            from paths import resolve_game_dir

            game_dir = resolve_game_dir()
        except FileNotFoundError:
            return False
    game_dir = Path(game_dir)
    dll = game_dir / "mod" / "dll" / DLL_NAME
    me3 = game_dir / "me3" / "convergence.me3"
    if not dll.is_file() or not me3.is_file():
        return False
    text = me3.read_text(encoding="utf-8", errors="replace")
    return _me3_has_package(text) and _me3_has_natives(text)


def build_preview(game_dir: Path) -> list[PreviewItem]:
    game_dir = Path(game_dir)
    items: list[PreviewItem] = []
    dll_dst = game_dir / "mod" / "dll" / DLL_NAME
    src = find_dll_source()
    if src:
        items.append(
            PreviewItem(
                "覆盖写入" if dll_dst.is_file() else "新建",
                str(dll_dst),
                f"来源 {src}",
            )
        )
    else:
        items.append(
            PreviewItem("失败", str(dll_dst), "找不到预编译 cnv_pickup_hook.dll")
        )
    me3 = game_dir / "me3" / "convergence.me3"
    if me3.is_file():
        text = me3.read_text(encoding="utf-8", errors="replace")
        if not _me3_has_package(text):
            items.append(PreviewItem("插入 package", str(me3), PACKAGE_ID))
        else:
            items.append(PreviewItem("已有 package", str(me3), PACKAGE_ID))
        if not _me3_has_natives(text):
            items.append(PreviewItem("插入 natives", str(me3), NATIVES_PATH))
        else:
            items.append(PreviewItem("已有 natives", str(me3), NATIVES_PATH))
        items.append(
            PreviewItem(
                "备份",
                str(me3.parent / "convergence.me3.cnvbak-<时间戳>"),
                "写入前备份",
            )
        )
    else:
        items.append(PreviewItem("失败", str(me3), "缺少 convergence.me3"))
    shell = game_dir / "mod" / "cnv_enemy"
    items.append(
        PreviewItem(
            "确保目录" if not shell.is_dir() else "目录已在",
            str(shell),
            "敌人叠加空壳",
        )
    )
    return items


def _insert_me3_blocks(text: str) -> str:
    out = text
    if not _me3_has_package(out):
        # After first [[package]] block if any, else append
        m = re.search(r"\[\[package\]\]", out)
        if m:
            # find end of first package-ish section: next [[ or EOF
            start = m.start()
            rest = out[start:]
            nxt = re.search(r"\n\[\[", rest[2:])  # skip current
            if nxt:
                insert_at = start + 2 + nxt.start()
                out = out[:insert_at] + "\n" + PACKAGE_BLOCK + out[insert_at:]
            else:
                out = out.rstrip() + "\n\n" + PACKAGE_BLOCK
        else:
            out = out.rstrip() + "\n\n" + PACKAGE_BLOCK
    if not _me3_has_natives(out):
        out = out.rstrip() + "\n\n" + NATIVES_BLOCK
    return out if out.endswith("\n") else out + "\n"


def _remove_me3_blocks(text: str) -> str:
    # Remove package block with our id (from [[package]] through blank line or next [[)
    def strip_package(s: str) -> str:
        pattern = re.compile(
            r"\n?#?[^\n]*\n?\[\[package\]\]\s*\n"
            r"(?:[^\[]*?)"
            rf'id\s*=\s*["\']{re.escape(PACKAGE_ID)}["\']'
            r"(?:.*?)(?=\n\[\[|\Z)",
            flags=re.IGNORECASE | re.DOTALL,
        )
        return pattern.sub("\n", s)

    def strip_natives(s: str) -> str:
        pattern = re.compile(
            r"\n?#?[^\n]*cnv_pickup[^\n]*\n?\[\[natives\]\]\s*\n"
            r"[^\[]*?cnv_pickup_hook\.dll[^\n]*\n?",
            flags=re.IGNORECASE,
        )
        # Simpler: [[natives]] ... path ... cnv_pickup_hook.dll
        pattern2 = re.compile(
            r"\[\[natives\]\]\s*\n[^\[]*?cnv_pickup_hook\.dll[^\n]*\n?",
            flags=re.IGNORECASE,
        )
        s2 = pattern.sub("\n", s)
        return pattern2.sub("", s2)

    out = strip_package(text)
    out = strip_natives(out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out if out.endswith("\n") else out + "\n"


def install_mod(
    game_dir: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> InstallResult:
    game_dir = Path(game_dir)
    report = detect_all(game_dir)
    msgs: list[str] = []
    preview = build_preview(game_dir)

    if report.process_running:
        return InstallResult(
            False,
            [report.process_detail or "游戏相关进程在运行，禁止安装"],
            preview,
        )

    if not report.er.ok and not force:
        return InstallResult(
            False,
            [report.er.detail, "勾选「强制安装试试」后才能继续"],
            preview,
        )
    if not report.cnv.likely_ok and not force:
        return InstallResult(
            False,
            [report.cnv.detail, "勾选「强制安装试试」后才能继续"],
            preview,
        )
    if force and (not report.er.ok or not report.cnv.likely_ok):
        msgs.append("已强制安装（版本警告已忽略）")

    src = find_dll_source()
    if src is None:
        return InstallResult(False, ["找不到预编译 cnv_pickup_hook.dll（bin/）"], preview)
    me3 = game_dir / "me3" / "convergence.me3"
    if not me3.is_file():
        return InstallResult(False, ["缺少 me3/convergence.me3"], preview)

    if dry_run:
        return InstallResult(True, ["预览通过（未写入）"] + msgs, preview)

    dll_dir = game_dir / "mod" / "dll"
    dll_dir.mkdir(parents=True, exist_ok=True)
    dst = dll_dir / DLL_NAME
    shutil.copy2(src, dst)
    msgs.append(f"已写入 {dst}")

    (game_dir / "mod" / "cnv_enemy").mkdir(parents=True, exist_ok=True)
    msgs.append(f"已确保目录 {game_dir / 'mod' / 'cnv_enemy'}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = me3.with_name(f"convergence.me3.cnvbak-{stamp}")
    shutil.copy2(me3, bak)
    msgs.append(f"已备份 {bak.name}")

    text = me3.read_text(encoding="utf-8", errors="replace")
    new_text = _insert_me3_blocks(text)
    if new_text != text:
        me3.write_text(new_text, encoding="utf-8", newline="\n")
        msgs.append("已更新 convergence.me3（补全 package/natives）")
    else:
        msgs.append("convergence.me3 已含本 mod 标记，未重复插入")

    save_path = save_game_dir(game_dir)
    msgs.append(f"已记住游戏目录 → {save_path}")

    if not is_mod_installed(game_dir):
        return InstallResult(False, msgs + ["安装后校验失败（标记或 dll 未齐）"], preview)
    msgs.append("校验通过：已装")
    return InstallResult(True, msgs, preview)


def uninstall_mod(
    game_dir: Path,
    *,
    remove_dll: bool = True,
) -> InstallResult:
    game_dir = Path(game_dir)
    preview = build_preview(game_dir)
    msgs: list[str] = []
    running, detail = _process_running()
    if running:
        return InstallResult(False, [detail], preview)

    me3 = game_dir / "me3" / "convergence.me3"
    if me3.is_file():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        bak = me3.with_name(f"convergence.me3.cnvbak-uninstall-{stamp}")
        shutil.copy2(me3, bak)
        text = me3.read_text(encoding="utf-8", errors="replace")
        new_text = _remove_me3_blocks(text)
        me3.write_text(new_text, encoding="utf-8", newline="\n")
        msgs.append(f"已从 me3 撤下本 mod 标记（备份 {bak.name}）")
    else:
        msgs.append("无 convergence.me3，跳过 me3 编辑")

    dll = game_dir / "mod" / "dll" / DLL_NAME
    if remove_dll and dll.is_file():
        dll.unlink()
        msgs.append(f"已删除 {dll}")
    elif dll.is_file():
        msgs.append("保留 dll（未勾选删除）")

    msgs.append("未删除 mod/cnv_enemy 地图（按契约默认保留）")
    return InstallResult(True, msgs, preview)
