"""导出同池出场占比 → reports/同池出场占比_当前.md"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from _pool_share_stats import (
    donor_npc_from_spawn,
    fmt_band_table,
    identify_structural_tail_npcs,
    load_pool_npc_slot_caps,
    top_end_band,
    top_end_band_fair_only,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SPAWN = SCRIPT_DIR / "output/runtime/cnv_enemy_spawn_map.txt"
WL = SCRIPT_DIR.parent / "捐皮契约/捐皮白名单_当前.json"
CATEGORIES = SCRIPT_DIR / "enemy_categories.json"
CAPS_JSON = SCRIPT_DIR / "cache/pool_npc_slot_caps.json"
OUT = SCRIPT_DIR.parent / "reports/同池出场占比_当前.md"

POOL_ZH = {1: "路边小怪", 2: "精英", 3: "洞穴Boss", 4: "场地Boss", 5: "红灵", 6: "主线大Boss"}
TGT_TO_POOL = {
    "trash": 1,
    "elite": 2,
    "minor_boss": 3,
    "evergaol": 4,
    "night": 5,
    "major_boss": 6,
}
TGT_ORDER = ["trash", "elite", "minor_boss", "evergaol", "night", "major_boss"]
BAND_N = 10


def main() -> None:
    categories_cfg = json.loads(CATEGORIES.read_text(encoding="utf-8"))
    slot_caps = load_pool_npc_slot_caps(CAPS_JSON)
    tail_by_tgt = {
        tgt: identify_structural_tail_npcs(slot_caps.get(tgt, {}), categories_cfg, tgt)
        for tgt in TGT_ORDER
    }

    rows: list[list[str]] = []
    seed = ""
    for line in SPAWN.read_text(encoding="utf-8").splitlines():
        if line.startswith("seed="):
            seed = line.split("=", 1)[1]
        elif line and not line.startswith("#") and "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 13:
                rows.append(parts)

    wl = json.loads(WL.read_text(encoding="utf-8"))
    name_by_npc: dict[str, str] = {}
    pool_by_npc: dict[str, int] = {}
    wl_pool_npcs: dict[int, set[str]] = defaultdict(set)
    for pool_s, pool_rows in wl.get("rows_by_pool", {}).items():
        for r in pool_rows:
            npc = str(r.get("npc"))
            name_by_npc[npc] = str(r.get("name_zh") or r.get("name_en") or npc).strip()
            pool_by_npc[npc] = int(pool_s)
            wl_pool_npcs[int(pool_s)].add(npc)

    by_tgt_npc: dict[str, Counter[str]] = defaultdict(Counter)
    tgt_totals: Counter[str] = Counter()
    tpl_by: dict[tuple[str, str], str] = {}
    for r in rows:
        tgt = r[3]
        npc = donor_npc_from_spawn(r, tgt)
        tpl = r[4]
        by_tgt_npc[tgt][npc] += 1
        tgt_totals[tgt] += 1
        tpl_by[(tgt, npc)] = tpl

    lines: list[str] = [
        f"# 同池出场占比（种子 {seed}）",
        "",
        "分母 = **该目标池槽位总数**；占比 = 该皮在本池出现次数 / 本池总槽。",
        "synthetic 契约行按 **template 名** 解析 donor npc（末列 npc 对 P5 等不可靠）。",
        f"**Top{BAND_N}/End{BAND_N}**：出场次数排序的前/后 {BAND_N} 皮；**公平均比** = 排除结构尾皮后 Top÷End。",
        "",
        "## 总览",
        "",
        f"| 池 | 槽位 | WL | 覆盖 | σ% | Top{BAND_N}均% | End{BAND_N}均% | 均比 | 公平均比 | 尾皮 | 未覆盖 |",
        "|:---|---:|---:|:---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]

    pool_sections: list[str] = []

    for tgt in TGT_ORDER:
        p = TGT_TO_POOL[tgt]
        total = tgt_totals[tgt]
        wl_npcs = wl_pool_npcs[p]
        counter = by_tgt_npc[tgt]
        appeared_wl = {npc for npc in counter if npc in wl_npcs}
        missing = sorted(wl_npcs - set(counter.keys()), key=lambda x: int(x))

        pcts_wl = [100 * counter[n] / total for n in appeared_wl] if total and appeared_wl else []
        sd = statistics.pstdev(pcts_wl) if len(pcts_wl) > 1 else 0.0
        band = top_end_band(counter, total, n=BAND_N)
        fair_band = top_end_band_fair_only(counter, total, tail_by_tgt[tgt], n=BAND_N)
        miss_n = len(missing)

        lines.append(
            f"| P{p} {POOL_ZH[p]} | {total} | {len(wl_npcs)} | "
            f"{len(appeared_wl)}/{len(wl_npcs)} | {sd:.2f} | "
            f"{band.top_avg_pct:.2f} | {band.end_avg_pct:.2f} | {band.ratio:.2f} | "
            f"{fair_band.ratio:.2f} | {len(tail_by_tgt[tgt])} | {miss_n} |"
        )

        sec: list[str] = [
            f"## P{p} {POOL_ZH[p]}",
            "",
            f"目标槽 **{total}** · 白名单 **{len(wl_npcs)}** 种 · "
            f"本池出场 **{len(appeared_wl)}** 种 · 结构尾皮 **{len(tail_by_tgt[tgt])}** 种 · "
            f"白名单未出 **{miss_n}** 种 · σ **{sd:.2f}%**",
            "",
            f"- **Top{band.n} 均占比** {band.top_avg_pct:.2f}%（合计 {band.top_sum_pct:.2f}%）",
            f"- **End{band.n} 均占比** {band.end_avg_pct:.2f}%（合计 {band.end_sum_pct:.2f}%）",
            f"- **均比** Top÷End = **{band.ratio:.2f}**",
            f"- **公平均比**（排除尾皮）= **{fair_band.ratio:.2f}** "
            f"(T{fair_band.top_avg_pct:.2f}% / E{fair_band.end_avg_pct:.2f}%)",
            "",
        ]
        sec.extend(
            fmt_band_table(
                band, total, name_by_npc, title=f"Top{band.n}", rows=band.top
            )
        )
        sec.extend(
            fmt_band_table(
                band, total, name_by_npc, title=f"End{band.n}", rows=band.end
            )
        )
        if missing:
            sec.append("### 白名单未覆盖")
            sec.append("")
            sec.append("| npc | 中文名 |")
            sec.append("|---:|:---|")
            for npc in missing:
                sec.append(f"| {npc} | {name_by_npc.get(npc, npc)} |")
            sec.append("")

        sec.append("### 全量出场排序")
        sec.append("")
        sec.append("| 占比 | 次数 | npc | 中文名 | 捐皮池 | model |")
        sec.append("|---:|---:|---:|:---|:---|:---|")
        for npc, c in counter.most_common():
            zh = name_by_npc.get(npc, f"npc {npc}")
            wp = pool_by_npc.get(npc, 0)
            pool_label = f"P{wp}" if wp else "—"
            cross = "跨池" if wp and wp != p else ""
            tpl = tpl_by.get((tgt, npc), "")
            mdl = tpl.split(":", 1)[-1].split("_")[0] if ":" in tpl else tpl
            if tpl.startswith("synthetic:"):
                m = re.search(r"(c\d+)", tpl)
                mdl = m.group(1) if m else mdl
            sec.append(
                f"| {100 * c / total:.2f}% | {c} | {npc} | {zh} | {pool_label} | "
                f"`{mdl}`{' · ' + cross if cross else ''} |"
            )
        sec.append("")
        pool_sections.extend(sec)

    lines.extend(["", "---", ""] + pool_sections)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
