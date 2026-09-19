"""归档契约禁捐：熔炉魔像 c5170 + 满月女王 c2030/c2031（不随机不捐皮）。

用法:
  python _archive_contract_bans.py
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
    enrich_donor_row,
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
CATEGORIES_PATH = SCRIPT_DIR / "enemy_categories.json"
ALLOWLIST_PATH = SCRIPT_DIR / "donor_pool_review_allowlist.json"

BAN_REASON = "不随机不捐皮"
BAN_MODELS = frozenset({"c5170", "c2030", "c2031"})
BAN_NPCS = frozenset({51701084, 20300024, 20310024})

_POOL_DETAIL_RE = re.compile(r"^## 池 \d+ ·")


def _flatten_by_pool(data: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    raw = data.get("rows_by_pool") or {}
    return {int(k): list(v) for k, v in raw.items()}


def _sort_pool_rows(by_pool: dict[int, list[dict[str, Any]]]) -> None:
    for rows in by_pool.values():
        rows.sort(
            key=lambda r: (
                -int(r.get("effective_hp") or 0),
                str(r.get("name_zh") or r.get("name_en") or ""),
                str(r.get("model") or ""),
            )
        )


def _md_intro_before_pool_details(md_text: str) -> str:
    lines = md_text.splitlines()
    for i, line in enumerate(lines):
        if _POOL_DETAIL_RE.match(line):
            return "\n".join(lines[:i]).rstrip() + "\n"
    return md_text


def _enrich_ban_row(
    *,
    pool: int,
    category: str,
    model: str,
    npc: int,
    name_zh: str,
    name_en: str,
    ctx: dict[str, Any],
    synthetic: bool = False,
) -> dict[str, Any]:
    extra = enrich_donor_row(
        {"npc": npc, "model": model, "template_id": ""},
        categories_cfg=ctx["categories_cfg"],
        npc_rows=ctx["npc_rows"],
        sp_rates=ctx["sp_rates"],
        paramdex_names=ctx["paramdex_names"],
        review_name_zh=ctx["review_name_zh"],
        archetype_index=ctx["archetype_index"],
        vanilla_npc_by_model=ctx.get("vanilla_npc_by_model") or {},
    )
    tier_id, tier_zh = resolve_size_tier_zh(model, categories_cfg=ctx["categories_cfg"])
    return {
        "pool": pool,
        "pool_zh": core.CATEGORY_DISPLAY_ZH.get(category, category),
        "category": category,
        "reason": "contract_block",
        "reason_zh": BAN_REASON,
        "model": model,
        "name_zh": name_zh or extra.get("name_zh") or "",
        "name_en": name_en or extra.get("name_en") or "",
        "effective_hp": int(extra.get("effective_hp") or 0),
        "hp_mult_desc": str(extra.get("hp_mult_desc") or ""),
        "npc": npc,
        "archetype_zh": extra.get("archetype_zh", ""),
        "size_tier": tier_id,
        "size_tier_zh": tier_zh,
        "synthetic": synthetic,
    }


def _upsert_blacklist_row(
    by_pool: dict[int, list[dict[str, Any]]],
    row: dict[str, Any],
) -> None:
    pool = int(row["pool"])
    npc = int(row["npc"])
    model = str(row.get("model") or "").lower()
    for p, rows in list(by_pool.items()):
        kept = []
        for existing in rows:
            if int(existing.get("npc") or 0) == npc or (
                str(existing.get("model") or "").lower() == model
                and str(existing.get("name_zh") or "") == str(row.get("name_zh") or "")
            ):
                continue
            kept.append(existing)
        by_pool[p] = kept
    by_pool.setdefault(pool, []).append(row)


def _remove_from_whitelist(by_pool: dict[int, list[dict[str, Any]]]) -> int:
    removed = 0
    for pool, rows in list(by_pool.items()):
        kept = []
        for r in rows:
            model = str(r.get("model") or "").lower()
            npc = int(r.get("npc") or 0)
            if model in BAN_MODELS or npc in BAN_NPCS:
                removed += 1
                continue
            kept.append(r)
        by_pool[pool] = kept
    return removed


def _update_categories(data: dict[str, Any]) -> None:
    for key in (
        "never_donor_model_prefixes",
        "exclude_slot_model_prefixes",
        "boss_pool_exclude_donor_prefixes",
    ):
        lst = list(data.get(key) or [])
        for mp in sorted(BAN_MODELS):
            if mp not in lst:
                lst.append(mp)
        data[key] = lst

    for key in ("never_donor_npc_ids", "exclude_slot_npc_ids"):
        ids = {int(x) for x in (data.get(key) or [])}
        ids |= BAN_NPCS
        data[key] = sorted(ids)

    synth = list(data.get("boss_pool_exclude_synthetic_template_ids") or [])
    for tid in ("synthetic:rennala_c2030", "synthetic:dlc_boss_c5170"):
        if tid not in synth:
            synth.append(tid)
    data["boss_pool_exclude_synthetic_template_ids"] = synth

    defs = {
        "exclude_slot_mount_definition": (
            "…柳条人影树化身(c5230)/熔炉魔像(c5170)/DLC山妖拉车(c5390~2)等槽位保持原位，"
            "不参与随机；满月女王 c2030/c2031（2026-09-01 不随机不捐）"
        ),
        "never_donor_npc_ids_definition": data.get("never_donor_npc_ids_definition", "")
        + "；**熔炉魔像** c5170 npc 51701084（2026-09-01 不随机不捐）",
        "boss_pool_exclude_donor_definition": (
            "…柳条人/影树化身(c5230)；**熔炉魔像(c5170)**；DLC山妖拉车(c5390~2)；"
            "**满月女王** c2030/c2031 + synthetic:rennala_c2030（2026-09-01 用户：不随机不捐）。"
            "碎星 c4730 仍按白名单可捐（流星风险另验）。"
        ),
    }
    for k, v in defs.items():
        if k in data or k.endswith("_definition"):
            data[k] = v


def _update_allowlist(data: dict[str, Any]) -> None:
    for cat in list(data.keys()):
        if not isinstance(data.get(cat), list):
            continue
        ids = [int(x) for x in data[cat] if int(x) not in BAN_NPCS]
        data[cat] = sorted(set(ids))
    note = str(data.get("note") or "")
    if "c5170" not in note:
        data["note"] = note + " | 2026-09-01: ban c5170 furnace golem 不随机不捐"


def _patch_md_ban_note(intro: str, *, for_whitelist: bool) -> str:
    if for_whitelist:
        ban_line = (
            "**禁捐不随机（2026-09-01）**：柳条人（影树化身 `c5230`）· "
            "熔炉魔像（`c5170`）· 满月女王蕾娜菈（`c2030`/`c2031`）— 已移出本表，见黑名单"
        )
    else:
        ban_line = (
            "**禁捐不随机（2026-09-01）**：柳条人（影树化身 `c5230`）· "
            "熔炉魔像（`c5170`）· 满月女王蕾娜菈（`c2030`/`c2031`）— 不随机不捐皮"
        )
    if "禁捐不随机" in intro:
        intro = re.sub(
            r"\*\*禁捐不随机[^\n]*\*\*[^\n]*",
            ban_line,
            intro,
            count=1,
        )
    else:
        intro = intro.rstrip() + "\n" + ban_line + "  \n"
    return intro


def main() -> None:
    ctx = load_donor_export_context()
    from dlc_donor_pool import build_vanilla_donor_npc_by_model

    index = core.load_enemy_index()
    ctx["vanilla_npc_by_model"] = build_vanilla_donor_npc_by_model(
        index.get("templates") or [],
        npc_by_id=ctx["npc_rows"],
        sp_rates=ctx["sp_rates"],
    )

    wl = json.loads(WL_JSON.read_text(encoding="utf-8"))
    bl = json.loads(BL_JSON.read_text(encoding="utf-8"))
    wl_by_pool = _flatten_by_pool(wl)
    bl_by_pool = _flatten_by_pool(bl)

    removed = _remove_from_whitelist(wl_by_pool)
    print(f"removed from whitelist: {removed}")

    _upsert_blacklist_row(
        bl_by_pool,
        _enrich_ban_row(
            pool=4,
            category="evergaol",
            model="c5170",
            npc=51701084,
            name_zh="熔炉魔像（青蓝海岸西南·卡罗隐藏墓地）",
            name_en="Furnace Golem (Southwest Cerulean Coast - Charo's Hidden Grave)",
            ctx=ctx,
            synthetic=True,
        ),
    )
    _upsert_blacklist_row(
        bl_by_pool,
        _enrich_ban_row(
            pool=6,
            category="major_boss",
            model="c2030",
            npc=20300024,
            name_zh="满月女王蕾娜菈（一阶段）",
            name_en="Rennala- Queen of the Full Moon",
            ctx=ctx,
        ),
    )
    _upsert_blacklist_row(
        bl_by_pool,
        _enrich_ban_row(
            pool=6,
            category="major_boss",
            model="c2031",
            npc=20310024,
            name_zh="满月女王蕾娜菈（二阶段）",
            name_en="Rennala- Queen of the Full Moon",
            ctx=ctx,
        ),
    )

    _sort_pool_rows(wl_by_pool)
    _sort_pool_rows(bl_by_pool)

    wl_total = sum(len(v) for v in wl_by_pool.values())
    bl_total = sum(len(v) for v in bl_by_pool.values())
    wl["rows_after_dedupe"] = wl_total
    wl["rows_by_pool"] = {str(p): rows for p, rows in sorted(wl_by_pool.items())}
    bl["rows_after_dedupe"] = bl_total
    bl["rows_by_pool"] = {str(p): rows for p, rows in sorted(bl_by_pool.items())}

    WL_JSON.write_text(json.dumps(wl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    BL_JSON.write_text(json.dumps(bl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    wl_intro = _patch_md_ban_note(
        _md_intro_before_pool_details(WL_MD.read_text(encoding="utf-8")),
        for_whitelist=True,
    )
    bl_intro = _patch_md_ban_note(
        _md_intro_before_pool_details(BL_MD.read_text(encoding="utf-8")),
        for_whitelist=False,
    )
    WL_MD.write_text(
        wl_intro + "\n".join(render_whitelist_pool_sections(wl_by_pool)).lstrip("\n") + "\n",
        encoding="utf-8",
    )
    BL_MD.write_text(
        bl_intro + "\n".join(render_blacklist_pool_sections(bl_by_pool)).lstrip("\n") + "\n",
        encoding="utf-8",
    )

    cat = json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))
    _update_categories(cat)
    CATEGORIES_PATH.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    allow = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    _update_allowlist(allow)
    ALLOWLIST_PATH.write_text(json.dumps(allow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"whitelist={wl_total} blacklist={bl_total}")
    print("wrote contract + enemy_categories + allowlist")


if __name__ == "__main__":
    main()
