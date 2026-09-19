"""导出当前运行时捐皮白名单（按 1～6 池 · 同名去重 · 与黑名单表同版式）。

用法:
  python _export_effective_donor_pool.py

输出:
  捐皮契约/捐皮白名单_当前.md
  捐皮契约/捐皮白名单_当前.json
"""
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
    render_whitelist_pool_sections,
    resolve_display_name_zh,
)
from dlc_donor_pool import build_vanilla_donor_npc_by_model  # noqa: E402
from enemy_slot_prep import build_prep_context  # noqa: E402
from paths import DONOR_POOL_CONTRACT_DIR  # noqa: E402

OUT_DIR = DONOR_POOL_CONTRACT_DIR
OUT_JSON = "捐皮白名单_当前.json"
OUT_MD = "捐皮白名单_当前.md"


def _export_progress(_phase: str, done: int, total: int, msg: str) -> None:
    if done in (0, total) or done % 200 == 0 or "仍在运行" in msg:
        print(msg, flush=True)


def main() -> None:
    ctx = load_donor_export_context()
    categories_cfg = ctx["categories_cfg"]
    archetype_index = ctx["archetype_index"]
    curated_names = load_curated_display_names()

    print("敌人：加载索引…", flush=True)
    index = core.load_enemy_index()
    print("敌人：重建捐皮 compat 池…", flush=True)
    prep = build_prep_context(
        index,
        categories_cfg,
        dlc_pool_mode="mixed",
        npc_csv_dir=ctx["npc_csv_dir"],
        on_progress=_export_progress,
    )
    vanilla_npc_by_model = build_vanilla_donor_npc_by_model(
        list(index.get("templates") or []),
        npc_by_id=ctx["npc_rows"],
        sp_rates=ctx["sp_rates"],
    )

    raw_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for pool_key, tpl_list in prep["compat_pools"].items():
        cat = pool_key[0] if isinstance(pool_key, tuple) else str(pool_key)
        for tpl in tpl_list:
            model = str(tpl.get("model", ""))
            try:
                npc = int(tpl.get("npc", 0) or 0)
            except (TypeError, ValueError):
                npc = 0
            tpl_cat = str(tpl.get("category") or cat)
            key = (tpl_cat, model.lower(), npc)
            if key in seen:
                continue
            seen.add(key)

            extra = enrich_donor_row(
                tpl,
                categories_cfg=categories_cfg,
                npc_rows=ctx["npc_rows"],
                sp_rates=ctx["sp_rates"],
                paramdex_names=ctx["paramdex_names"],
                review_name_zh=ctx["review_name_zh"],
                archetype_index=archetype_index,
                vanilla_npc_by_model=vanilla_npc_by_model,
            )
            pool = int(core.CATEGORY_NUM.get(tpl_cat, 0) or 0)
            tid = str(tpl.get("template_id") or "")
            raw_rows.append(
                {
                    "pool": pool,
                    "pool_zh": core.CATEGORY_DISPLAY_ZH.get(tpl_cat, tpl_cat),
                    "category": tpl_cat,
                    "model": model,
                    "name_zh": resolve_display_name_zh(
                        extra["name_en"], extra, curated_names=curated_names
                    ),
                    "name_en": extra["name_en"],
                    "effective_hp": extra["effective_hp"],
                    "hp_mult_desc": extra["hp_mult_desc"],
                    "npc": npc,
                    "archetype_zh": extra["archetype_zh"],
                    "size_tier": extra["size_tier"],
                    "size_tier_zh": extra["size_tier_zh"],
                    "synthetic": tid.startswith("synthetic:"),
                }
            )

    by_pool_name: dict[tuple[int, str], dict[str, Any]] = {}
    for row in raw_rows:
        pool = int(row["pool"])
        if pool <= 0:
            continue
        k = (pool, name_key(row))
        if k in by_pool_name:
            by_pool_name[k] = pick_better_row_by_hp(by_pool_name[k], row)
        else:
            by_pool_name[k] = row

    by_pool: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for (pool, _nk), row in by_pool_name.items():
        by_pool[pool].append(row)
    for pool in by_pool:
        by_pool[pool].sort(
            key=lambda r: (
                str(r.get("name_zh") or r.get("name_en") or r.get("model") or ""),
                str(r.get("model") or ""),
            )
        )

    total_rows = sum(len(v) for v in by_pool.values())
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print(f"敌人：写出白名单 {total_rows} 种…", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / OUT_JSON
    json_path.write_text(
        json.dumps(
            {
                "generated_at": generated,
                "schema": "donor_whitelist_v1",
                "raw_distinct_model_npc": len(raw_rows),
                "rows_after_dedupe": total_rows,
                "by_category": {
                    cat: sum(1 for r in raw_rows if r["category"] == cat)
                    for cat in core.CATEGORY_ORDER
                },
                "rows_by_pool": {str(p): rows for p, rows in sorted(by_pool.items())},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lines: list[str] = [
        "# 捐皮白名单（按池 · 简化）",
        "",
        f"**生成**：{generated}  ",
        f"**条数**：{total_rows} 种（池内中文/英文名去重；原始 {len(raw_rows)} 条 model+npc）  ",
        "**口径**：`build_prep_context` → `compat_pools`（审阅白名单 + 运行时禁捐过滤后）  ",
        "**1 池升格**：有效 HP ≥4000→2 精英 · ≥10000→3 洞穴Boss · ≥14000→4 场地Boss（`trash_donor_hp_promotion`）  ",
        "**中文名**：`donor_blacklist_name_zh.json` 人工校对优先  ",
        "**对照黑名单**：`捐皮黑名单_当前.md`  ",
        f"**机器可读**：`{OUT_JSON}`",
        "",
        "> 现网 **6 池**（`CATEGORY_ORDER`）：1 路边小怪 · 2 精英 · 3 洞穴Boss · 4 场地Boss · 5 红灵 · 6 主线大Boss。",
        "",
        "## 池概览",
        "",
        "| 池 | 类 | 白名单捐皮（去重后） |",
        "|---:|:---|---:|",
    ]
    for pool_num, _cat_id, pool_title in pool_sections():
        lines.append(f"| {pool_num} | {pool_title} | {len(by_pool.get(pool_num, []))} |")

    lines.extend(render_whitelist_pool_sections(by_pool))

    md_path = OUT_DIR / OUT_MD
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {md_path} rows={total_rows} raw={len(raw_rows)}")
    print(f"wrote {json_path}")


if __name__ == "__main__":
    main()
