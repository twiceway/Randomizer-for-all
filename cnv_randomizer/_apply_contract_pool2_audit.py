"""一次性：池2 审计 → 更新 捐皮契约/ 黑白名单（仅改契约，不实装）。"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import enemy_randomizer_core as core  # noqa: E402
from _donor_export_common import (  # noqa: E402
    enrich_donor_row,
    load_curated_display_names,
    load_donor_export_context,
    name_key,
    pick_better_row_by_hp,
    pool_sections,
    render_blacklist_pool_sections,
    render_whitelist_pool_sections,
    resolve_display_name_zh,
)
from paths import DONOR_POOL_CONTRACT_DIR  # noqa: E402

WL_JSON = DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.json"
BL_JSON = DONOR_POOL_CONTRACT_DIR / "捐皮黑名单_当前.json"

# 池2 审计序号 → npc（初版表行号，按 npc 落地）
REMOVE_WL_NPC = frozenset({50600083, 58800091, 50900080, 56410083})
FORCE_POOL1_NPC = frozenset(
    {57001083, 57000083, 42500150, 42500028, 42000043, 55600050, 55600093, 57600080}
)
HP_FIX_POOL2: dict[int, tuple[int, str]] = {
    51930094: (9700, "20007013×9.7~代理51920100"),
    58300093: (2390, "20007090×12.446"),
}
BLACKLIST_REASON: dict[int, str] = {
    50600083: "不捐不随机（池2审计）",
    58800091: "不捐不随机（池2审计）",
    50900080: "不捐不随机（池2审计）",
    56410083: "不捐可随机（池2审计）",
}


def _flatten_by_pool(data: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    raw = data.get("rows_by_pool") or {}
    return {int(k): list(v) for k, v in raw.items()}


def _write_whitelist_md(by_pool: dict[int, list[dict[str, Any]]], total: int) -> None:
    lines = [
        "# 捐皮白名单（按池 · 简化）",
        "",
        "**位置**：`捐皮契约/`（人工审计真源；**非** `reports/` 机器导出）  ",
        "**状态**：审计中 — 直接改本表；全池审完后一次性实装  ",
        f"**池2审计**：2026-08-05（4·19·21 不捐不随机 · 6·29·30·40·61·63·131→池1 · 39·69 HP · 112 不捐可随机）  ",
        f"**条数**：{total} 种  ",
        "**对照黑名单**：`捐皮黑名单_当前.md`  ",
        "**机器可读**：`捐皮白名单_当前.json`",
        "",
        "> 现网 **6 池**：1 路边小怪 · 2 精英 · 3 洞穴Boss · 4 场地Boss · 5 红灵 · 6 主线大Boss。",
        "",
        "## 池概览",
        "",
        "| 池 | 类 | 白名单捐皮（去重后） |",
        "|---:|:---|---:|",
    ]
    for pool_num, _cat_id, pool_title in pool_sections():
        lines.append(f"| {pool_num} | {pool_title} | {len(by_pool.get(pool_num, []))} |")
    lines.extend(render_whitelist_pool_sections(by_pool))
    (DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _write_blacklist_md(by_pool: dict[int, list[dict[str, Any]]], total: int) -> None:
    lines = [
        "# 捐皮黑名单（按池 · 简化）",
        "",
        "**位置**：`捐皮契约/`（人工审计真源；**非** `reports/` 机器导出）  ",
        "**状态**：审计中 — 直接改本表；全池审完后一次性实装  ",
        f"**池2审计**：2026-08-05  ",
        f"**条数**：{total} 种  ",
        "**对照白名单**：`捐皮白名单_当前.md`  ",
        "**机器可读**：`捐皮黑名单_当前.json`",
        "",
        "> 禁捐且白名单无同名；「不捐可随机」槽位仍可被换皮。",
        "",
        "## 池概览",
        "",
        "| 池 | 类 | 黑名单（去重后） |",
        "|---:|:---|---:|",
    ]
    for pool_num, _cat_id, pool_title in pool_sections():
        lines.append(f"| {pool_num} | {pool_title} | {len(by_pool.get(pool_num, []))} |")
    lines.extend(render_blacklist_pool_sections(by_pool))
    (DONOR_POOL_CONTRACT_DIR / "捐皮黑名单_当前.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _enrich_npc_row(npc: int, *, pool: int, category: str, ctx: dict[str, Any]) -> dict[str, Any]:
    curated = ctx.get("curated") or {}
    npc_rows = ctx["npc_rows"]
    row = npc_rows.get(npc) or {}
    model = str(row.get("model") or row.get("Model") or "")
    extra = enrich_donor_row(
        {"npc": npc, "model": model, "template_id": ""},
        categories_cfg=ctx["categories_cfg"],
        npc_rows=npc_rows,
        sp_rates=ctx["sp_rates"],
        paramdex_names=ctx["paramdex_names"],
        review_name_zh=ctx["review_name_zh"],
        archetype_index=ctx["archetype_index"],
        vanilla_npc_by_model=ctx.get("vanilla_npc_by_model") or {},
    )
    cat = category
    return {
        "pool": pool,
        "pool_zh": core.CATEGORY_DISPLAY_ZH.get(cat, cat),
        "category": cat,
        "model": model or extra.get("model") or "",
        "name_zh": resolve_display_name_zh(extra["name_en"], extra, curated_names=curated),
        "name_en": extra["name_en"],
        "effective_hp": extra["effective_hp"],
        "hp_mult_desc": extra["hp_mult_desc"],
        "npc": npc,
        "archetype_zh": extra.get("archetype_zh", ""),
        "size_tier": extra.get("size_tier", ""),
        "size_tier_zh": extra.get("size_tier_zh", ""),
        "synthetic": False,
    }


def main() -> None:
    ctx = load_donor_export_context()
    ctx["curated"] = load_curated_display_names()
    from dlc_donor_pool import build_vanilla_donor_npc_by_model

    index = core.load_enemy_index()
    ctx["vanilla_npc_by_model"] = build_vanilla_donor_npc_by_model(
        index.get("templates") or [],
        npc_by_id=ctx["npc_rows"],
        sp_rates=ctx["sp_rates"],
    )

    wl = json.loads(WL_JSON.read_text(encoding="utf-8"))
    by_pool = _flatten_by_pool(wl)
    removed_for_bl: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []

    for pool, rows in by_pool.items():
        for r in rows:
            npc = int(r.get("npc") or 0)
            if npc in REMOVE_WL_NPC:
                removed_for_bl.append(dict(r))
                continue
            row = dict(r)
            if npc in FORCE_POOL1_NPC:
                row["pool"] = 1
                row["category"] = "trash"
                row["pool_zh"] = core.CATEGORY_DISPLAY_ZH.get("trash", "路边小怪")
            if npc in HP_FIX_POOL2 and int(row.get("pool") or 0) == 2:
                hp, desc = HP_FIX_POOL2[npc]
                row["effective_hp"] = hp
                row["hp_mult_desc"] = desc
            all_rows.append(row)

    # 确保降池1 条目在白名单池1
    present = {int(r.get("npc") or 0) for r in all_rows}
    for npc in FORCE_POOL1_NPC:
        if npc in present or npc in REMOVE_WL_NPC:
            continue
        all_rows.append(_enrich_npc_row(npc, pool=1, category="trash", ctx=ctx))

    by_pool_name: dict[tuple[int, str], dict[str, Any]] = {}
    for row in all_rows:
        pool = int(row["pool"])
        k = (pool, name_key(row))
        if k in by_pool_name:
            by_pool_name[k] = pick_better_row_by_hp(by_pool_name[k], row)
        else:
            by_pool_name[k] = row

    new_by_pool: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for (pool, _nk), row in by_pool_name.items():
        new_by_pool[pool].append(row)
    for pool in new_by_pool:
        new_by_pool[pool].sort(
            key=lambda r: (
                str(r.get("name_zh") or r.get("name_en") or ""),
                str(r.get("model") or ""),
            )
        )

    total_wl = sum(len(v) for v in new_by_pool.values())
    wl["rows_after_dedupe"] = total_wl
    wl["rows_by_pool"] = {str(p): rows for p, rows in sorted(new_by_pool.items())}
    WL_JSON.write_text(json.dumps(wl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_whitelist_md(dict(new_by_pool), total_wl)

    bl = json.loads(BL_JSON.read_text(encoding="utf-8"))
    bl_by_pool = _flatten_by_pool(bl)
    bl_npc = {int(r.get("npc") or 0) for rows in bl_by_pool.values() for r in rows}

    for r in removed_for_bl:
        npc = int(r.get("npc") or 0)
        reason = BLACKLIST_REASON.get(npc, "池2审计剔除")
        pool = 2
        bl_row = dict(r)
        bl_row["pool"] = pool
        bl_row["reason"] = "manual_audit"
        bl_row["reason_zh"] = reason
        if npc not in bl_npc:
            bl_by_pool.setdefault(pool, []).append(bl_row)
            bl_npc.add(npc)

    for npc, reason in BLACKLIST_REASON.items():
        if npc in bl_npc:
            for rows in bl_by_pool.values():
                for r in rows:
                    if int(r.get("npc") or 0) == npc:
                        r["reason_zh"] = reason
            continue
        bl_by_pool.setdefault(2, []).append(
            {
                **_enrich_npc_row(npc, pool=2, category="elite", ctx=ctx),
                "reason": "manual_audit",
                "reason_zh": reason,
            }
        )
        bl_npc.add(npc)

    for pool in bl_by_pool:
        bl_by_pool[pool].sort(
            key=lambda r: (
                str(r.get("name_zh") or r.get("name_en") or ""),
                str(r.get("model") or ""),
            )
        )
    total_bl = sum(len(v) for v in bl_by_pool.values())
    bl["rows_after_dedupe"] = total_bl
    bl["rows_by_pool"] = {str(p): rows for p, rows in sorted(bl_by_pool.items())}
    BL_JSON.write_text(json.dumps(bl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_blacklist_md(dict(bl_by_pool), total_bl)

    print(f"whitelist rows: {total_wl}")
    print(f"blacklist rows: {total_bl}")
    print(f"removed from wl: {[int(r['npc']) for r in removed_for_bl]}")


if __name__ == "__main__":
    main()
