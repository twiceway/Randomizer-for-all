"""筛选后捐皮审阅表 → 运行时捐皮白名单（审阅 md 仍分 7 档；现网 `CATEGORY_ORDER` 为 6 池）。"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from paths import FILTERED_DONOR_REVIEW_DIR, REPO_ROOT

from paths import SCRIPT_DIR as _SCRIPT_DIR  # frozen-safe
_CACHE_JSON = _SCRIPT_DIR / "donor_pool_review_allowlist.json"
_MANUAL_INCLUDES_PATH = _SCRIPT_DIR / "donor_pool_review_manual_includes.json"

# 审阅池序号 → 运行时 category（与 GUI 行/列顺序一致）
REVIEW_POOL_TO_CATEGORY: dict[int, str] = {
    1: "trash",
    2: "elite",
    3: "minor_boss",
    4: "evergaol",
    5: "evergaol",
    6: "night",
    7: "major_boss",
}

CATEGORY_TO_REVIEW_POOL: dict[str, int] = {
    v: k for k, v in REVIEW_POOL_TO_CATEGORY.items()
}

# 旧 id 迁移（矩阵 / 绑定 / 存档）
LEGACY_CATEGORY_ALIASES: dict[str, str] = {
    "cnv_special": "major_boss",
    "field_boss": "evergaol",
}

REVIEW_POOL_GLOBS: dict[int, list[str]] = {
    1: ["捐皮池表_池1_*.md"],
    2: ["捐皮池表_池2_精英.md"],
    3: [
        "捐皮池表_池3_洞穴副本boss.md",
        "捐皮池表_池3_骑兵类.md",
        "捐皮池表_池3_minor_boss.md",
    ],
    4: ["捐皮池表_池4_封印监牢boss.md"],
    5: ["捐皮池表_池5_次要boss.md"],
    6: ["捐皮池表_池6_红灵.md"],
    7: ["捐皮池表_池7_主线大boss.md"],
}


def normalize_category_id(cat: str) -> str:
    c = str(cat or "").strip()
    return LEGACY_CATEGORY_ALIASES.get(c, c)


def migrate_category_weights(
    weights: dict[str, dict[str, float]] | None,
) -> dict[str, dict[str, float]]:
    """cnv_special / field_boss 行列并入 major_boss / evergaol；补 elite 对角行。"""
    if not weights:
        return {}
    out: dict[str, dict[str, float]] = {}
    for src_raw, row in weights.items():
        if not isinstance(row, dict):
            continue
        src = normalize_category_id(str(src_raw))
        merged: dict[str, float] = out.get(src, {})
        for tgt_raw, w in row.items():
            try:
                val = float(w)
            except (TypeError, ValueError):
                continue
            if val <= 0:
                continue
            tgt = normalize_category_id(str(tgt_raw))
            merged[tgt] = merged.get(tgt, 0.0) + val
        if merged:
            out[src] = merged
    if "elite" not in out:
        out["elite"] = {"elite": 100.0}
    return out


def _header_npc_index(header_line: str) -> int | None:
    parts = [p.strip() for p in header_line.split("|")]
    for i, name in enumerate(parts):
        if name == "npc":
            return i
    return None


def _parse_md_npcs(path: Path) -> set[int]:
    if not path.is_file():
        return set()
    npc_idx: int | None = None
    out: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        if "序号" in line and "npc" in line:
            npc_idx = _header_npc_index(line)
            continue
        if line.startswith("| ---"):
            continue
        if npc_idx is None:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) <= npc_idx:
            continue
        try:
            int(parts[1])  # 序号列
        except (TypeError, ValueError):
            continue
        raw = parts[npc_idx].strip()
        if not raw or raw == "npc":
            continue
        try:
            out.add(int(raw))
        except (TypeError, ValueError):
            continue
    return out


def _pool_paths(pool: int, base: Path) -> list[Path]:
    paths: list[Path] = []
    for pattern in REVIEW_POOL_GLOBS.get(pool, []):
        for p in sorted(base.glob(pattern)):
            name = p.name
            if pool == 1 and name in {
                "捐皮池表_池1_索引.md",
                "捐皮池表_池1_trash.md",
            }:
                continue
            if "索引" in name:
                continue
            paths.append(p)
    return paths


@lru_cache(maxsize=1)
def load_manual_includes() -> tuple[dict[str, frozenset[int]], dict[int, str]]:
    """人工补录白名单：(按类 npc 集, npc→强制类别)。"""
    if not _MANUAL_INCLUDES_PATH.is_file():
        return {}, {}
    try:
        data = json.loads(_MANUAL_INCLUDES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    by_cat: dict[str, set[int]] = {}
    override: dict[int, str] = {}
    for entry in data.get("entries") or []:
        try:
            npc = int(entry.get("npc", 0) or 0)
        except (TypeError, ValueError):
            continue
        if npc <= 0:
            continue
        cat = normalize_category_id(str(entry.get("category") or ""))
        if not cat:
            continue
        by_cat.setdefault(cat, set()).add(npc)
        override[npc] = cat
    return (
        {k: frozenset(v) for k, v in by_cat.items()},
        override,
    )


def _merge_allowlist_maps(
    base: dict[str, frozenset[int]],
) -> dict[str, frozenset[int]]:
    manual_by_cat, _ = load_manual_includes()
    cats = set(base) | set(manual_by_cat)
    return {
        cat: frozenset(base.get(cat, ())) | manual_by_cat.get(cat, frozenset())
        for cat in cats
    }


def build_allowlist_from_review_md(
    base: Path | None = None,
) -> dict[str, set[int]]:
    base = base or FILTERED_DONOR_REVIEW_DIR
    by_cat: dict[str, set[int]] = {c: set() for c in REVIEW_POOL_TO_CATEGORY.values()}
    for pool, cat in REVIEW_POOL_TO_CATEGORY.items():
        npcs: set[int] = set()
        for md in _pool_paths(pool, base):
            npcs |= _parse_md_npcs(md)
        by_cat[cat] = npcs
    return _merge_allowlist_maps({k: frozenset(v) for k, v in by_cat.items()})


def export_allowlist_json(
    out_path: Path | None = None,
    *,
    base: Path | None = None,
) -> Path:
    out_path = out_path or _CACHE_JSON
    by_cat = build_allowlist_from_review_md(base)
    payload = {
        "source": str(base or FILTERED_DONOR_REVIEW_DIR),
        "manual_includes": str(_MANUAL_INCLUDES_PATH) if _MANUAL_INCLUDES_PATH.is_file() else "",
        "pool_to_category": REVIEW_POOL_TO_CATEGORY,
        "npc_ids_by_category": {k: sorted(v) for k, v in by_cat.items()},
        "counts": {k: len(v) for k, v in by_cat.items()},
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


@lru_cache(maxsize=1)
def load_review_allowlist_by_category() -> dict[str, frozenset[int]]:
    if _CACHE_JSON.is_file():
        try:
            data = json.loads(_CACHE_JSON.read_text(encoding="utf-8"))
            raw = data.get("npc_ids_by_category") or {}
            return _merge_allowlist_maps(
                {
                    str(k): frozenset(int(x) for x in v)
                    for k, v in raw.items()
                }
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    built = build_allowlist_from_review_md()
    try:
        export_allowlist_json(_CACHE_JSON)
    except OSError:
        pass
    return _merge_allowlist_maps({k: frozenset(v) for k, v in built.items()})


def donor_category_for_npc(
    npc: int,
    *,
    allowlist: dict[str, frozenset[int]] | None = None,
) -> str | None:
    """npc 落在哪个审阅池；多池命中时取序号最大（更 Boss）。"""
    if npc <= 0:
        return None
    _, overrides = load_manual_includes()
    if npc in overrides:
        return overrides[npc]
    allowlist = allowlist if allowlist is not None else load_review_allowlist_by_category()
    best_pool = 0
    best_cat = ""
    for pool in sorted(REVIEW_POOL_TO_CATEGORY):
        cat = REVIEW_POOL_TO_CATEGORY[pool]
        if npc in allowlist.get(cat, ()):
            if pool >= best_pool:
                best_pool = pool
                best_cat = cat
    return best_cat or None


def apply_review_allowlist_category(
    tpl: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    allowlist: dict[str, frozenset[int]] | None = None,
) -> str | None:
    """按筛选白名单覆写 template 捐皮类别；不在白名单返回 None。"""
    if not categories_cfg.get("donor_review_allowlist_enabled", False):
        return str(tpl.get("category") or "") or None
    try:
        npc = int(tpl.get("npc", 0) or 0)
    except (TypeError, ValueError):
        return None
    allowlist = allowlist if allowlist is not None else load_review_allowlist_by_category()
    tpl_id = str(tpl.get("template_id", ""))
    if tpl_id.startswith("synthetic:contract_"):
        cat = normalize_category_id(str(tpl.get("category") or ""))
        if cat and npc in allowlist.get(cat, ()):
            tpl["category"] = cat
            return cat
    cat = donor_category_for_npc(npc, allowlist=allowlist)
    if not cat:
        return None
    tpl["category"] = cat
    return cat

def is_allowlisted_donor_template(
    tpl: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> bool:
    if not categories_cfg.get("donor_review_allowlist_enabled", False):
        return True
    try:
        npc = int(tpl.get("npc", 0) or 0)
    except (TypeError, ValueError):
        return False
    return donor_category_for_npc(npc) is not None
