"""T-084 R3 — load / fingerprint bundle export tables for prep synthesis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bundle_export_common import file_fingerprint
from donor_pool_review_allowlist import normalize_category_id

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
BUNDLE_CATALOG_PATH = SCRIPT_DIR / "cache" / "bundle_catalog.json"
SLOT_TAGS_PATH = SCRIPT_DIR / "cache" / "slot_tags.json"
BUNDLE_SLOT_COMPAT_PATH = SCRIPT_DIR / "cache" / "bundle_slot_compat.json"
REEXPORT_HINT = "请先运行 cnv_randomizer\\REEXPORT_DONOR.bat 重建捐皮导出表"


class BundleExportError(RuntimeError):
    """Bundle export cache missing or stale."""


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def bundle_export_fingerprints() -> dict[str, str]:
    return {
        "bundle_catalog": file_fingerprint(BUNDLE_CATALOG_PATH),
        "slot_tags": file_fingerprint(SLOT_TAGS_PATH),
        "bundle_slot_compat": file_fingerprint(BUNDLE_SLOT_COMPAT_PATH),
    }


def _fingerprint_mismatch(
    label: str,
    path: Path,
    stored: str,
    current: str,
) -> str | None:
    if current == "missing":
        return f"缺少 {label}（{path.name}）"
    if stored and stored != current:
        return f"{label} 指纹过期（{stored[:8]}→{current[:8]}）"
    return None


def validate_bundle_exports_for_prep(
    *,
    expected: dict[str, str] | None = None,
) -> None:
    """Hard gate before prep synthesis or generate; raises BundleExportError."""
    fps = bundle_export_fingerprints()
    missing = [k for k, v in fps.items() if v == "missing"]
    if missing:
        raise BundleExportError(
            f"捐皮 Bundle 导出表未就绪（缺 {', '.join(missing)}）。{REEXPORT_HINT}"
        )
    if expected is None:
        return
    parts: list[str] = []
    path_by_key = {
        "bundle_catalog": BUNDLE_CATALOG_PATH,
        "slot_tags": SLOT_TAGS_PATH,
        "bundle_slot_compat": BUNDLE_SLOT_COMPAT_PATH,
    }
    for key, path in path_by_key.items():
        msg = _fingerprint_mismatch(
            path.name,
            path,
            str(expected.get(key, "")),
            fps[key],
        )
        if msg:
            parts.append(msg)
    if parts:
        raise BundleExportError("；".join(parts) + f"。{REEXPORT_HINT}")


def load_bundle_catalog(path: Path | None = None) -> dict[str, Any]:
    path = path or BUNDLE_CATALOG_PATH
    if not path.is_file():
        raise BundleExportError(f"缺少 {path.name}。{REEXPORT_HINT}")
    return _load_json(path)


def load_slot_tags(path: Path | None = None) -> dict[str, Any]:
    path = path or SLOT_TAGS_PATH
    if not path.is_file():
        raise BundleExportError(f"缺少 {path.name}。{REEXPORT_HINT}")
    return _load_json(path)


def load_bundle_slot_compat(path: Path | None = None) -> dict[str, Any]:
    path = path or BUNDLE_SLOT_COMPAT_PATH
    if not path.is_file():
        raise BundleExportError(f"缺少 {path.name}。{REEXPORT_HINT}")
    return _load_json(path)


def compat_by_tid_from_bundle_slot_compat(
    payload: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    payload = payload or load_bundle_slot_compat()
    out: dict[str, dict[str, Any]] = {}
    for bid, entry in (payload.get("bundles") or {}).items():
        compat = dict((entry or {}).get("compat") or {})
        if compat:
            out[str(bid)] = compat
    return out


def index_templates_by_id(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for tpl in index.get("templates") or []:
        tid = str(tpl.get("template_id") or "")
        if tid:
            out[tid] = tpl
    return out


def bundle_to_template(
    bundle_id: str,
    bundle: dict[str, Any],
    index_tpl: dict[str, Any] | None,
) -> dict[str, Any]:
    tpl = dict(index_tpl) if index_tpl else {}
    tpl["template_id"] = bundle_id
    tpl["model"] = str(bundle.get("model") or tpl.get("model") or "")
    tpl["npc"] = bundle.get("npc", tpl.get("npc"))
    tpl["think"] = bundle.get("think", tpl.get("think"))
    tpl["chara"] = bundle.get("chara", tpl.get("chara", -1))
    tpl["category"] = normalize_category_id(
        str(bundle.get("src_category") or tpl.get("category") or "")
    )
    walk = str(
        bundle.get("donor_walk_route")
        or tpl.get("walk_route")
        or tpl.get("donor_walk_route")
        or ""
    ).strip()
    if walk:
        tpl["walk_route"] = walk
        tpl["donor_walk_route"] = walk
    return tpl


def templates_by_cat_from_bundle_catalog(
    catalog: dict[str, Any],
    index: dict[str, Any],
    categories_cfg: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build donor templates_by_cat from bundle_catalog (no full-index scan)."""
    from enemy_randomizer_core import CATEGORY_ORDER

    _ = categories_cfg
    by_id = index_templates_by_id(index)
    templates_by_cat: dict[str, list[dict[str, Any]]] = {
        c: [] for c in CATEGORY_ORDER
    }
    for bundle_id, bundle in (catalog.get("bundles") or {}).items():
        cat = normalize_category_id(str(bundle.get("src_category") or ""))
        if cat not in templates_by_cat:
            continue
        tpl = bundle_to_template(str(bundle_id), bundle, by_id.get(str(bundle_id)))
        templates_by_cat[cat].append(tpl)
    return templates_by_cat
