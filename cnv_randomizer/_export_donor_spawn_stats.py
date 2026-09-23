"""导出当前 spawn_map 捐皮出场次数/占比 → output/reports/捐皮出场统计_当前.md"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from paths import DONOR_POOL_CONTRACT_DIR, OUTPUT_REPORTS  # noqa: E402

SPAWN = SCRIPT_DIR / "output" / "runtime" / "cnv_enemy_spawn_map.txt"
WL_JSON = DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.json"
OUT = OUTPUT_REPORTS / "捐皮出场统计_当前.md"

POOL_ZH = {
    1: "路边小怪",
    2: "精英",
    3: "洞穴Boss",
    4: "场地Boss",
    5: "红灵",
    6: "主线大Boss",
}
TGT_ZH = {
    "trash": "路边",
    "elite": "精英",
    "minor_boss": "洞穴Boss",
    "evergaol": "场地Boss",
    "night": "红灵",
    "major_boss": "主线Boss",
}


def skin_model(tpl: str) -> str:
    if tpl.startswith("synthetic:"):
        m = re.search(r"(c\d+)", tpl)
        return m.group(1) if m else tpl
    if ":" in tpl:
        return tpl.split(":", 1)[1].split("_")[0]
    return tpl


def main() -> None:
    rows: list[list[str]] = []
    seed = ""
    for line in SPAWN.read_text(encoding="utf-8").splitlines():
        if line.startswith("seed="):
            seed = line.split("=", 1)[1]
        elif line and not line.startswith("#") and "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 13:
                rows.append(parts)

    wl = json.loads(WL_JSON.read_text(encoding="utf-8"))
    name_by_npc: dict[str, str] = {}
    pool_by_npc: dict[str, int] = {}
    for pool_s, pool_rows in wl.get("rows_by_pool", {}).items():
        for r in pool_rows:
            npc = str(r.get("npc"))
            name_by_npc[npc] = str(r.get("name_zh") or r.get("name_en") or npc).strip()
            pool_by_npc[npc] = int(pool_s)

    n = len(rows)
    by_npc = Counter(r[12] for r in rows)
    by_tgt = Counter(r[3] for r in rows)
    tpl_by_npc = {r[12]: r[4] for r in rows}

    lines: list[str] = [
        f"# 捐皮出场统计（种子 {seed}）",
        "",
        f"总替换槽：**{n}** · 不同捐皮 **{len(by_npc)}** 种",
        "",
        "## 按目标池（抽中后落在哪类）",
        "",
        "| 目标池 | 槽数 | 占比 |",
        "|:---|---:|---:|",
    ]
    for cat, c in by_tgt.most_common():
        lines.append(f"| {TGT_ZH.get(cat, cat)} | {c} | {100 * c / n:.2f}% |")

    lines += [
        "",
        "## 按捐皮（全表 · 次数降序）",
        "",
        "| 占比 | 次数 | 白名单池 | 中文名 | model |",
        "|---:|---:|:---|:---|:---|",
    ]
    for npc, c in by_npc.most_common():
        zh = name_by_npc.get(npc, f"（未在白名单）npc {npc}")
        pool = pool_by_npc.get(npc, 0)
        pool_label = f"P{pool} {POOL_ZH.get(pool, '')}" if pool else "—"
        mdl = skin_model(tpl_by_npc[npc])
        lines.append(
            f"| {100 * c / n:.2f}% | {c} | {pool_label} | {zh} | `{mdl}` |"
        )

    lines += [
        "",
        "## 按白名单池汇总",
        "",
        "| 池 | 出场次数 | 占全图 | 用到的皮种类 |",
        "|:---|---:|---:|---:|",
    ]
    by_pool_count: dict[int, int] = defaultdict(int)
    by_pool_slots: dict[int, int] = defaultdict(int)
    for npc, c in by_npc.items():
        p = pool_by_npc.get(npc, 0) or 0
        by_pool_count[p] += 1
        by_pool_slots[p] += c
    for p in range(1, 7):
        if by_pool_slots[p]:
            lines.append(
                f"| P{p} {POOL_ZH[p]} | {by_pool_slots[p]} | "
                f"{100 * by_pool_slots[p] / n:.1f}% | {by_pool_count[p]} |"
            )

    top10 = sum(c for _, c in by_npc.most_common(10))
    top20 = sum(c for _, c in by_npc.most_common(20))
    once = sum(1 for c in by_npc.values() if c == 1)
    lines += [
        "",
        "## 集中度",
        f"- 前 10 名捐皮合计：**{100 * top10 / n:.1f}%**",
        f"- 前 20 名捐皮合计：**{100 * top20 / n:.1f}%**",
        f"- 只出现 1 次的皮：**{once}** 种",
        "",
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
