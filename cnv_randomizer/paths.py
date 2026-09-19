"""Resolve Game install directory + repo path constants.

发行包（sys.frozen）：exe 在包根，同级 ``data/`` 为 REPO_ROOT，
``cnv_randomizer`` 在 ``data/cnv_randomizer``（SCRIPT_DIR）。契约见 ``.ai/docs/发行包契约.md``。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def subprocess_no_window_kwargs() -> dict[str, Any]:
    """Windows: hide console when a GUI app launches console EXEs (no focus steal)."""
    if sys.platform != "win32":
        return {}
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return {"creationflags": flag}


def _detect_roots() -> tuple[Path, Path]:
    """Return (SCRIPT_DIR, REPO_ROOT)."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        # 现网：包根 RandomizerForAll.exe + 同级 data/
        flat = exe_dir / "data"
        if (flat / "cnv_randomizer").is_dir():
            return flat / "cnv_randomizer", flat
        # 旧包兼容：app/RandomizerForAll.exe → ../data/
        nested = exe_dir.parent / "data"
        if (nested / "cnv_randomizer").is_dir():
            return nested / "cnv_randomizer", nested
        meipass = Path(getattr(sys, "_MEIPASS", exe_dir))
        return meipass, meipass
    script_dir = Path(__file__).resolve().parent
    return script_dir, script_dir.parent


SCRIPT_DIR, REPO_ROOT = _detect_roots()

# Generated artifacts (gitignored subsets — see root .gitignore)
OUTPUT_DIR = SCRIPT_DIR / "output"
OUTPUT_RUNTIME = OUTPUT_DIR / "runtime"
OUTPUT_REPORTS = REPO_ROOT / "reports"
# 捐皮黑白名单人工审计真源（与 reports/ 机器统计表分离）
DONOR_POOL_CONTRACT_DIR = REPO_ROOT / "捐皮契约"
OUTPUT_AUDIT = OUTPUT_DIR / "audit"
CACHE_DIR = SCRIPT_DIR / "cache"
DOCS_DIR = SCRIPT_DIR / "docs"
# 捐皮/原槽审阅（用户手工审阅，与 reports/ 分离）
DONOR_POOL_REVIEW_DIR = REPO_ROOT / "捐池_原槽表"
FILTERED_SLOT_REVIEW_DIR = DONOR_POOL_REVIEW_DIR / "筛选后槽表"
FILTERED_DONOR_REVIEW_DIR = DONOR_POOL_REVIEW_DIR / "筛选后捐池表"


def ensure_donor_review_dirs() -> None:
    for path in (
        DONOR_POOL_REVIEW_DIR,
        FILTERED_SLOT_REVIEW_DIR,
        FILTERED_DONOR_REVIEW_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def ensure_donor_contract_dir() -> None:
    DONOR_POOL_CONTRACT_DIR.mkdir(parents=True, exist_ok=True)


def ensure_output_dirs() -> None:
    for path in (OUTPUT_RUNTIME, OUTPUT_REPORTS, OUTPUT_AUDIT, OUTPUT_DIR / "logs"):
        path.mkdir(parents=True, exist_ok=True)
    ensure_donor_contract_dir()


def resolve_output_dir(
    cfg: dict | None = None,
    *,
    output_dir: str | Path | None = None,
) -> Path:
    """Resolve config ``output_dir`` (default ``output/runtime``) under SCRIPT_DIR."""
    if output_dir is not None:
        path = Path(output_dir)
    elif cfg:
        path = Path(str(cfg.get("output_dir", "output/runtime")))
    else:
        path = OUTPUT_RUNTIME
    return path if path.is_absolute() else SCRIPT_DIR / path


# False = not yet resolved / miss (re-probe next call). Path = hit.
# Never sticky-cache "not found": install may write game_path.json later in the same process.
_GAME_DIR_CACHE: Path | bool = False


def clear_game_dir_cache() -> None:
    """Drop memoized Game dir (call after user saves game_path.json)."""
    global _GAME_DIR_CACHE
    _GAME_DIR_CACHE = False


def try_resolve_game_dir() -> Path | None:
    """Best-effort Game dir; None if user has not configured yet (GUI first launch)."""
    global _GAME_DIR_CACHE
    if isinstance(_GAME_DIR_CACHE, Path):
        return _GAME_DIR_CACHE

    if env := os.environ.get("CNV_GAME_DIR"):
        path = Path(env)
        if path.is_dir():
            _GAME_DIR_CACHE = path
            return path
        return None

    deployed = SCRIPT_DIR.parent.parent
    if (deployed / "mod").is_dir():
        _GAME_DIR_CACHE = deployed
        return deployed

    for cfg_path in (
        SCRIPT_DIR / "game_path.json",
        REPO_ROOT / "game_path.json",
    ):
        if not cfg_path.is_file():
            continue
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        path = Path(str(data.get("game_dir", "")))
        if path.is_dir():
            _GAME_DIR_CACHE = path
            return path
        # File remembers a path that is not a directory right now — do not cache miss.
        return None
    return None


def resolve_game_dir() -> Path:
    """Resolve Elden Ring Game folder; raise if missing (generate/apply paths)."""
    found = try_resolve_game_dir()
    if found is not None:
        return found
    if env := os.environ.get("CNV_GAME_DIR"):
        raise FileNotFoundError(f"CNV_GAME_DIR is not a directory: {env}")
    for cfg_path in (
        SCRIPT_DIR / "game_path.json",
        REPO_ROOT / "game_path.json",
    ):
        if not cfg_path.is_file():
            continue
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        path = Path(str(data.get("game_dir", "")))
        raise FileNotFoundError(
            f"已记住的游戏文件夹无效或不存在：{path}\n"
            "请打开「安装」页重新选择含 eldenring.exe 的 Game 目录，并点「安装本mod到游戏」。"
        )
    raise FileNotFoundError(
        "还没选好游戏文件夹。\n"
        "请打开「安装」页，选择含 eldenring.exe 的 Game 目录，再点「安装本mod到游戏」。"
    )


class _LazyGamePath:
    """Path-like that resolves Game dir only when used (import-safe without game_path)."""

    __slots__ = ("_parts", "_cached")

    def __init__(self, *parts: str) -> None:
        self._parts = parts
        self._cached: Path | None = None

    def _resolved(self) -> Path:
        if self._cached is not None:
            return self._cached
        base = resolve_game_dir()
        self._cached = base.joinpath(*self._parts) if self._parts else base
        return self._cached

    def __truediv__(self, other: Any) -> _LazyGamePath:
        # Chain without resolving so ``GAME_DIR / "csv" / "x.csv"`` stays import-safe.
        if isinstance(other, _LazyGamePath):
            return _LazyGamePath(*self._parts, *other._parts)
        return _LazyGamePath(*self._parts, str(other))

    def __fspath__(self) -> str:
        return os.fspath(self._resolved())

    def __str__(self) -> str:
        try:
            return str(self._resolved())
        except FileNotFoundError:
            rel = "/".join(self._parts) if self._parts else ""
            return f"<GAME_DIR unset>{'/' + rel if rel else ''}"

    def __repr__(self) -> str:
        return f"_LazyGamePath{self._parts!r}"

    def __eq__(self, other: object) -> bool:
        try:
            return Path(self) == Path(other)  # type: ignore[arg-type]
        except (TypeError, FileNotFoundError, ValueError):
            return NotImplemented

    def joinpath(self, *args: Any) -> _LazyGamePath:
        parts = list(self._parts)
        for a in args:
            if isinstance(a, _LazyGamePath):
                parts.extend(a._parts)
            else:
                parts.append(str(a))
        return _LazyGamePath(*parts)

    def is_dir(self) -> bool:
        try:
            return self._resolved().is_dir()
        except FileNotFoundError:
            return False

    def is_file(self) -> bool:
        try:
            return self._resolved().is_file()
        except FileNotFoundError:
            return False

    def exists(self) -> bool:
        try:
            return self._resolved().exists()
        except FileNotFoundError:
            return False

    def resolve(self, strict: bool = False) -> Path:
        p = self._resolved()
        return p.resolve(strict=strict)

    def absolute(self) -> Path:
        return self._resolved().absolute()

    @property
    def parent(self) -> Path:
        return self._resolved().parent

    @property
    def name(self) -> str:
        if self._parts:
            return self._parts[-1]
        try:
            return self._resolved().name
        except FileNotFoundError:
            return "Game"

    def mkdir(self, parents: bool = False, exist_ok: bool = False) -> None:
        self._resolved().mkdir(parents=parents, exist_ok=exist_ok)

    def read_text(self, encoding: str = "utf-8", errors: str = "strict") -> str:
        return self._resolved().read_text(encoding=encoding, errors=errors)

    def write_text(
        self,
        data: str,
        encoding: str = "utf-8",
        errors: str = "strict",
        newline: str | None = None,
    ) -> int:
        return self._resolved().write_text(
            data, encoding=encoding, errors=errors, newline=newline
        )

    def read_bytes(self) -> bytes:
        return self._resolved().read_bytes()

    def write_bytes(self, data: bytes) -> int:
        return self._resolved().write_bytes(data)

    def open(self, *args: Any, **kwargs: Any):
        return self._resolved().open(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolved(), name)


# Import-safe: does not call resolve_game_dir until path is used.
GAME_DIR: Any = _LazyGamePath()
DEFAULT_RUNTIME_MAP: Any = _LazyGamePath("mod", "dll", "cnv_runtime_map.txt")
DEFAULT_ENEMY_SPAWN_MAP: Any = _LazyGamePath("mod", "dll", "cnv_enemy_spawn_map.txt")
