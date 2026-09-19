# -*- coding: utf-8 -*-
"""
P1-7: cache vs whitelist 对比脚本。

对比 cache/bundle_catalog.json 与 捐皮白名单（donor_pool_review_allowlist.json），
报告「白名单有但 cache 无」和「cache 有但白名单无」的条目。

用法：
  python _diff_bundle_cache.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent
WL_JSON = ROOT / "donor_pool_review_allowlist.json"
WL_MD = ROOT.parent / "捐皮契约" / "捐皮白名单_当前.json"
CACHE = ROOT / "cache" / "bundle_catalog.json"
REPORT = ROOT / "_diff_bundle_cache_report.md"


def main() -> None:
    # Load whitelist
    if WL_JSON.exists():
        wl = json.loads(WL_JSON.read_text(encoding="utf-8"))
        by_cat = wl.get("by_category") or {}
        note = wl.get("note", "")
    elif WL_MD.exists():
        # Fallback to md-source json if current json missing
        wl = json.loads(WL_MD.read_text(encoding="utf-8"))
        by_cat = wl.get("by_category") or {}
        note = wl.get("note", "")
    else:
        print("ERROR: 找不到白名单 JSON")
        return

    # Load bundle catalog
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    bundles = cache.get("bundles") or {}

    # Extract NPC IDs
    wl_npcs: dict[str, list[int]] = {}  # category -> npc list
    for cat, npcs in by_cat.items():
        wl_npcs[cat] = [int(n) for n in npcs]

    all_wl_npcs = {n for npcs in wl_npcs.values() for n in npcs}
    cache_npcs = {int(b["npc"]) for b in bundles.values()}

    # A: whitelist has but cache doesn't
    missing_from_cache = sorted(all_wl_npcs - cache_npcs)
    # B: cache has but whitelist doesn't
    missing_from_wl = sorted(cache_npcs - all_wl_npcs)

    # Map missing npcs to their categories (from whitelist)
    missing_from_cache_by_cat: dict[str, list[int]] = {}
    for npc in missing_from_cache:
        for cat, npcs in wl_npcs.items():
            if npc in npcs:
                missing_from_cache_by_cat.setdefault(cat, []).append(npc)
                break

    # Map missing cache npcs to bundle info
    cache_only: list[dict] = []
    for b in bundles.values():
        npc = int(b["npc"])
        if npc in missing_from_wl:
            cache_only.append({
                "npc": npc,
                "model": b.get("model", "?"),
                "name_zh": b.get("name_zh", "?"),
                "name_en": b.get("name_en", "?"),
                "src_category": b.get("src_category", "?"),
                "bundle_id": b.get("bundle_id", "?"),
            })

    # Build report
    lines: list[str] = []
    lines.append("# Cache vs Whitelist 对比报告")
    lines.append("")
    lines.append(f"生成时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"白名单：`donor_pool_review_allowlist.json`（白名单 NPC {len(all_wl_npcs)} 个）")
    lines.append(f"缓存：`cache/bundle_catalog.json`（bundle {len(bundles)} 个，涵盖 NPC {len(cache_npcs)} 个）")
    lines.append("")

    # A: missing from cache
    lines.append(f"## A. 白名单有 {len(missing_from_cache)} 个 NPC 但 cache 无 bundle")
    lines.append("")
    if missing_from_cache:
        lines.append("| 池 | npc | 备注 |")
        lines.append("|---:|---:|:---|")
        for cat, npcs in sorted(missing_from_cache_by_cat.items()):
            for npc in sorted(npcs):
                lines.append(f"| {cat} | {npc} | — |")
    else:
        lines.append("（无）")
    lines.append("")

    # B: missing from whitelist
    lines.append(f"## B. Cache 有 {len(cache_only)} 个 bundle 但白名单无该 NPC")
    lines.append("")
    if cache_only:
        lines.append("| npc | model | 中文名 | 英文名 | 源池 | bundle_id |")
        lines.append("|---:|:---|:---|:---|:---:|:---|")
        for r in sorted(cache_only, key=lambda x: x["npc"]):
            lines.append(
                f"| {r['npc']} | `{r['model']}` | {r['name_zh']} | "
                f"{r['name_en']} | {r['src_category']} | {r['bundle_id']} |"
            )
    else:
        lines.append("（无）")
    lines.append("")

    md = "\n".join(lines)
    REPORT.write_text(md, encoding="utf-8")
    print(f"报告已写：{REPORT}")
    print(f"  白名单有但 cache 无：{len(missing_from_cache)} 个")
    print(f"  cache 有但白名单无：{len(cache_only)} 个")


if __name__ == "__main__":
    main()
