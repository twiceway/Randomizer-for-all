"""为捐皮契约黑白名单 JSON/MD 补全体型列（size_tier_zh）。

用法:
  python _enrich_contract_size_tier.py

保留 MD 文件头部人工审计说明；仅重写各池明细表。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import enemy_randomizer_core as core  # noqa: E402
from _donor_export_common import (  # noqa: E402
    load_donor_export_context,
    render_blacklist_pool_sections,
    render_whitelist_pool_sections,
    resolve_size_tier_zh,
)
from paths import DONOR_POOL_CONTRACT_DIR  # noqa: E402

WL_JSON = DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.json"
BL_JSON = DONOR_POOL_CONTRACT_DIR / "捐皮黑名单_当前.json"
WL_MD = DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.md"
BL_MD = DONOR_POOL_CONTRACT_DIR / "捐皮黑名单_当前.md"

_POOL_DETAIL_RE = re.compile(r"^## 池 \d+ ·")


def _flatten_by_pool(data: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    raw = data.get("rows_by_pool") or {}
    return {int(k): list(v) for k, v in raw.items()}


def _enrich_rows(
    by_pool: dict[int, list[dict[str, Any]]],
    *,
    categories_cfg: dict[str, Any],
    archetype_index: core.ArchetypeIndex,
) -> None:
    for rows in by_pool.values():
        for row in rows:
            model = str(row.get("model") or "")
            tier_id, tier_zh = resolve_size_tier_zh(model, categories_cfg=categories_cfg)
            row["size_tier"] = tier_id
            row["size_tier_zh"] = tier_zh
            if not str(row.get("archetype_zh") or "").strip():
                arch_id = archetype_index.trash_archetype_for_model(model)
                if arch_id:
                    row["archetype_zh"] = archetype_index.trash_archetype_labels.get(
                        arch_id, ""
                    )


def _md_intro_before_pool_details(md_text: str) -> str:
    lines = md_text.splitlines()
    for i, line in enumerate(lines):
        if _POOL_DETAIL_RE.match(line):
            return "\n".join(lines[:i]).rstrip() + "\n"
    return md_text


def main() -> None:
    ctx = load_donor_export_context()
    categories_cfg = ctx["categories_cfg"]
    archetype_index = ctx["archetype_index"]

    wl = json.loads(WL_JSON.read_text(encoding="utf-8"))
    bl = json.loads(BL_JSON.read_text(encoding="utf-8"))
    wl_by_pool = _flatten_by_pool(wl)
    bl_by_pool = _flatten_by_pool(bl)

    _enrich_rows(wl_by_pool, categories_cfg=categories_cfg, archetype_index=archetype_index)
    _enrich_rows(bl_by_pool, categories_cfg=categories_cfg, archetype_index=archetype_index)

    for pool, rows in wl_by_pool.items():
        rows.sort(
            key=lambda r: (
                -int(r.get("effective_hp") or 0),
                str(r.get("name_zh") or r.get("name_en") or ""),
                str(r.get("model") or ""),
            )
        )
    for pool, rows in bl_by_pool.items():
        rows.sort(
            key=lambda r: (
                -int(r.get("effective_hp") or 0),
                str(r.get("name_zh") or r.get("name_en") or ""),
                str(r.get("model") or ""),
            )
        )

    wl["rows_by_pool"] = {str(p): rows for p, rows in sorted(wl_by_pool.items())}
    bl["rows_by_pool"] = {str(p): rows for p, rows in sorted(bl_by_pool.items())}

    WL_JSON.write_text(json.dumps(wl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    BL_JSON.write_text(json.dumps(bl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    wl_intro = _md_intro_before_pool_details(WL_MD.read_text(encoding="utf-8"))
    bl_intro = _md_intro_before_pool_details(BL_MD.read_text(encoding="utf-8"))
    WL_MD.write_text(
        wl_intro + "\n".join(render_whitelist_pool_sections(wl_by_pool)).lstrip("\n") + "\n",
        encoding="utf-8",
    )
    BL_MD.write_text(
        bl_intro + "\n".join(render_blacklist_pool_sections(bl_by_pool)).lstrip("\n") + "\n",
        encoding="utf-8",
    )

    wl_n = sum(len(v) for v in wl_by_pool.values())
    bl_n = sum(len(v) for v in bl_by_pool.values())
    wl_empty = sum(1 for rs in wl_by_pool.values() for r in rs if not r.get("size_tier_zh"))
    bl_empty = sum(1 for rs in bl_by_pool.values() for r in rs if not r.get("size_tier_zh"))
    print(f"whitelist rows={wl_n} empty_size_tier={wl_empty}")
    print(f"blacklist rows={bl_n} empty_size_tier={bl_empty}")
    print(f"wrote {WL_JSON.name} {BL_JSON.name} {WL_MD.name} {BL_MD.name}")


if __name__ == "__main__":
    main()
